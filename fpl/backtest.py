"""Backtest: do our SQL forecasts beat two simple baselines?

For every player-gameweek from `from_gw` on, four one-gameweek-ahead
predictions are scored against actual total_points (summed over a double
gameweek) by mean absolute error:

  model      v_xp.xp_model at as_of_gw = gw (uses only earlier gameweeks)
  v2         v_xp2.xp_v2 at as_of_gw = gw (forecast v2; calib_att fitted on
             meta.fit_season by fpl.fit, so scoring meta.backtest_season is out of sample)
  last5_avg  mean of the player's last 5 gameweek totals before gw
  fpl_ep     FPL's own pre-gameweek ep_pre

A row is scored only if the player was in a squad (minutes > 0 or
v_player_form.start_prob > 0) and ALL four predictions exist, so every
method is judged on identical rows.

A second, 3-gameweek check (ruling R22) scores the numbers behind the
transfer suggestions. For each start gameweek g with an FPL prediction and
g + 2 within the loaded season (38 for a complete season), each method
predicts points summed over g..g+2 using only gameweeks before g:

  model      sum of v_xp.xp_model over g..g+2 at as_of_gw = g
  v2         sum of v_xp2.xp_v2 over g..g+2 at as_of_gw = g
  last5_avg  last-5 average x number of fixtures in g..g+2
  fpl_ep     ep_pre at g x (sum of FDR multipliers over g..g+2) / (multiplier
             sum in g), as the app does (R20); the model when g has no fixture

The app's source is chosen per horizon (meta.forecast_source_1gw / _3gw): 'v2' only if
its MAE is strictly lower than every other method's in that table, otherwise the better
of fpl_ep and model as before (a tie goes to the model).
"""
import argparse
from pathlib import Path

from fpl import db

METHODS = ("model", "last5_avg", "fpl_ep", "v2")
LABELS = {"model": "SQL model v1 (v_xp)", "last5_avg": "Last-5 average", "fpl_ep": "FPL ep_pre",
          "v2": "Forecast v2 (v_xp2)"}
LABELS3 = {"model": "SQL model v1 (v_xp), summed over 3 GWs",
           "v2": "Forecast v2 (v_xp2), summed over 3 GWs",
           "last5_avg": "Last-5 average × fixtures",
           "fpl_ep": "FPL ep_pre, scaled over 3 GWs (R20)"}


def choose_source(table: dict) -> str:
    """'v2' only if its MAE is strictly lower than every other method's, else 'fpl_ep' if FPL's
    own number is the best of the old three, else 'model' (ties go to the model)."""
    valid = {m: table[m]["mae"] for m in METHODS if table[m]["n"] > 0}
    old = {m: v for m, v in valid.items() if m != "v2"}
    best_old = min(old, key=old.get) if old else "model"   # METHODS lists the model first
    if "v2" in valid and old and valid["v2"] < min(old.values()):
        return "v2"
    return "fpl_ep" if best_old == "fpl_ep" else "model"


def _score_one_gw(conn, season: str, from_gw: int) -> dict:
    """1-gameweek table for `season`. Leaves temp.bt_actual / bt_xp / bt_v2 for _three_gw;
    the caller drops them with _drop_temp."""
    _drop_temp(conn)
    # ep_pre is identical on both rows of a double gameweek in the archive
    # (checked), so MAX() just picks that single value; NULL if all NULL.
    conn.execute("""
        CREATE TEMP TABLE bt_actual AS
        SELECT player_id, gw, SUM(minutes) AS minutes,
               SUM(total_points) AS actual, MAX(ep_pre) AS ep_pre
        FROM player_gw WHERE season = ? GROUP BY player_id, gw
    """, (season,))
    conn.execute("CREATE INDEX temp.bt_actual_i ON bt_actual (player_id, gw)")
    conn.execute("""
        CREATE TEMP TABLE bt_xp AS
        SELECT x.player_id, x.gw, x.xp_model, f.start_prob
        FROM v_xp AS x
        JOIN v_player_form AS f
          ON f.season = x.season AND f.player_id = x.player_id AND f.as_of_gw = x.as_of_gw
        WHERE x.season = ? AND x.gw = x.as_of_gw AND x.gw >= ?
    """, (season, from_gw))
    conn.execute("CREATE INDEX temp.bt_xp_i ON bt_xp (player_id, gw)")
    # v2 forecast made at as_of_gw = g: for g itself, and summed over g..g+2. Materialised
    # once so the heavy v_xp2_fixture view runs a single time for both tables.
    conn.execute("""
        CREATE TEMP TABLE bt_v2 AS
        SELECT player_id, as_of_gw AS gw,
               SUM(CASE WHEN gw = as_of_gw THEN xp_v2 END) AS xp1,
               SUM(xp_v2) AS xp3
        FROM v_xp2_fixture
        WHERE season = ? AND as_of_gw >= ?
        GROUP BY player_id, as_of_gw
    """, (season, from_gw))
    conn.execute("CREATE INDEX temp.bt_v2_i ON bt_v2 (player_id, gw)")
    # last5_avg: mean of up to 5 most recent earlier gameweek totals;
    # players with no earlier gameweek have no baseline and are dropped.
    conn.execute("""
        CREATE TEMP TABLE bt_scored AS
        SELECT a.player_id, a.gw, a.actual, x.xp_model AS model, a.ep_pre AS fpl_ep,
               v.xp1 AS v2,
               (SELECT AVG(p.actual) FROM (
                    SELECT actual FROM bt_actual
                    WHERE player_id = a.player_id AND gw < a.gw
                    ORDER BY gw DESC LIMIT 5) AS p) AS last5_avg
        FROM bt_actual AS a
        JOIN bt_xp AS x ON x.player_id = a.player_id AND x.gw = a.gw
        JOIN bt_v2 AS v ON v.player_id = a.player_id AND v.gw = a.gw
        WHERE (a.minutes > 0 OR x.start_prob > 0)
          AND a.ep_pre IS NOT NULL AND a.actual IS NOT NULL
          AND x.xp_model IS NOT NULL AND v.xp1 IS NOT NULL
    """)
    where = "last5_avg IS NOT NULL"
    result = {}
    for m in METHODS:
        mae, n = conn.execute(
            f"SELECT AVG(ABS({m} - actual)), COUNT(*) FROM bt_scored WHERE {where}").fetchone()
        result[m] = {"mae": float(mae) if mae is not None else float("nan"), "n": int(n)}
    gws = conn.execute(f"SELECT MIN(gw), MAX(gw) FROM bt_scored WHERE {where}").fetchone()
    covered = [g for (g,) in conn.execute(
        f"SELECT DISTINCT gw FROM bt_scored WHERE {where} ORDER BY gw")]
    conn.execute("DROP TABLE temp.bt_scored")
    result.update(season=season, from_gw=from_gw, first_gw=gws[0], last_gw=gws[1],
                  covered_gws=covered)
    return result


def _drop_temp(conn):
    conn.executescript("""
        DROP TABLE IF EXISTS temp.bt_actual;
        DROP TABLE IF EXISTS temp.bt_xp;
        DROP TABLE IF EXISTS temp.bt_v2;
        DROP TABLE IF EXISTS temp.bt_scored;
        DROP TABLE IF EXISTS temp.bt_xp3;
        DROP TABLE IF EXISTS temp.bt_scored3;
    """)


def _set_meta(conn, key: str, value: str):
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def run(conn, season: str, from_gw: int = 6) -> dict:
    # Intermediate results live in TEMP tables so the heavy views run once.
    result = _score_one_gw(conn, season, from_gw)
    row = conn.execute("SELECT value FROM meta WHERE key = 'fit_season'").fetchone()
    result["fit_season"] = row[0] if row else "the earlier"
    result["three_gw"] = _three_gw(conn, season, from_gw)
    _drop_temp(conn)
    result["source_1gw"] = choose_source(result)
    result["source_3gw"] = choose_source(result["three_gw"])
    # winner = lowest MAE among the old three, unless v2 is strictly better than all of them
    old = {m: result[m]["mae"] for m in METHODS if m != "v2" and result[m]["n"] > 0}
    result["winner"] = "v2" if result["source_1gw"] == "v2" else (
        min(old, key=old.get) if old else "model")
    _set_meta(conn, "forecast_source_1gw", result["source_1gw"])
    _set_meta(conn, "forecast_source_3gw", result["source_3gw"])
    _set_meta(conn, "forecast_source", result["source_1gw"])      # kept for compatibility
    conn.commit()
    return result


def current_season_check(conn) -> dict | None:
    """Score the 1-gameweek methods on the current season's loaded gameweeks that have an FPL
    prediction (ep_pre, stored from the first gameweek with a snapshot). None while fewer than
    5 such gameweeks exist."""
    season = conn.execute("SELECT value FROM meta WHERE key = 'current_season'").fetchone()[0]
    r = _score_one_gw(conn, season, 6)
    _drop_temp(conn)
    if len(r["covered_gws"]) < 5:
        return None
    return r


def _three_gw(conn, season: str, from_gw: int) -> dict:
    """3-gameweek check (R22). Reads temp.bt_actual, bt_xp and bt_v2 from _score_one_gw()."""
    # model total, fixture count and FDR multipliers over g..g+2, forecast at as_of g
    conn.execute("""
        CREATE TEMP TABLE bt_xp3 AS
        SELECT player_id, as_of_gw AS gw,
               SUM(xp) AS xp3,
               SUM(fixture_id IS NOT NULL) AS fixtures3,
               SUM(CASE WHEN gw = as_of_gw THEN mult END) AS mult1,
               SUM(mult) AS mult3
        FROM v_xp_fixture
        WHERE season = ? AND as_of_gw >= ?
          AND as_of_gw + 2 <= (SELECT MAX(gw) FROM player_gw WHERE season = ?)
        GROUP BY player_id, as_of_gw
    """, (season, from_gw, season))
    conn.execute("CREATE INDEX temp.bt_xp3_i ON bt_xp3 (player_id, gw)")
    conn.execute("""
        CREATE TEMP TABLE bt_scored3 AS
        SELECT a.player_id, a.gw,
               (SELECT SUM(b.actual) FROM bt_actual AS b
                WHERE b.player_id = a.player_id AND b.gw BETWEEN a.gw AND a.gw + 2) AS actual,
               t.xp3 AS model, v.xp3 AS v2,
               CASE WHEN COALESCE(t.mult1, 0) > 0 THEN a.ep_pre * t.mult3 / t.mult1
                    ELSE t.xp3 END AS fpl_ep,
               t.fixtures3 * (SELECT AVG(p.actual) FROM (
                    SELECT actual FROM bt_actual
                    WHERE player_id = a.player_id AND gw < a.gw
                    ORDER BY gw DESC LIMIT 5) AS p) AS last5_avg
        FROM bt_actual AS a
        JOIN bt_xp AS x ON x.player_id = a.player_id AND x.gw = a.gw
        JOIN bt_xp3 AS t ON t.player_id = a.player_id AND t.gw = a.gw
        JOIN bt_v2 AS v ON v.player_id = a.player_id AND v.gw = a.gw
        WHERE (a.minutes > 0 OR x.start_prob > 0)
          AND a.ep_pre IS NOT NULL AND t.xp3 IS NOT NULL AND v.xp3 IS NOT NULL
    """)
    where = "last5_avg IS NOT NULL AND actual IS NOT NULL"
    out = {}
    for m in METHODS:
        mae, n = conn.execute(
            f"SELECT AVG(ABS({m} - actual)), COUNT(*) FROM bt_scored3 WHERE {where}").fetchone()
        out[m] = {"mae": float(mae) if mae is not None else float("nan"), "n": int(n)}
    out["starts"] = [g for (g,) in conn.execute(
        f"SELECT DISTINCT gw FROM bt_scored3 WHERE {where} ORDER BY gw")]
    conn.executescript("DROP TABLE temp.bt_scored3; DROP TABLE temp.bt_xp3;")
    return out


def _ranges(gws):
    out, start, prev = [], None, None
    for g in list(gws) + [None]:
        if start is None:
            start = prev = g
        elif g is not None and g == prev + 1:
            prev = g
        else:
            out.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = g
    return ", ".join(out) if gws else ""


SOURCE_TEXT = {
    "fpl_ep": "FPL's own prediction (ep)",
    "model": "our v1 SQL model",
    "v2": "forecast v2 (built from xG, xA, clean-sheet chance and DefCon chance)",
}


def _table(result_part: dict, labels: dict) -> str:
    return "\n".join(
        f"| {labels[m]} | {result_part[m]['mae']:.3f} | {result_part[m]['n']} |" for m in METHODS)


def _why(table: dict, source: str) -> str:
    """One sentence on why `source` was chosen for a horizon."""
    best_old = min((m for m in METHODS if m != "v2" and table[m]["n"] > 0),
                   key=lambda m: table[m]["mae"], default=None)
    if best_old is None:
        return "No rows could be scored, so the default is kept."
    if source == "v2":
        return (f"Forecast v2 had the lowest MAE ({table['v2']['mae']:.3f}), strictly below "
                f"the next best ({LABELS[best_old]}, {table[best_old]['mae']:.3f}).")
    return (f"Forecast v2 ({table['v2']['mae']:.3f}) was not strictly better than "
            f"{LABELS[best_old]} ({table[best_old]['mae']:.3f}), so v2 is not used here.")


def write_report(result: dict, path: Path) -> None:
    three = result["three_gw"]
    covered = result["covered_gws"]
    ranges = _ranges(covered)
    missing = [g for g in range(result["from_gw"], (result["last_gw"] or 0) + 1)
               if g not in covered]
    s1, s3 = result["source_1gw"], result["source_3gw"]
    scaling = (", scaled by how many fixtures the player has and how hard they are"
               if s3 == "fpl_ep" else "")
    fit = result.get("fit_season", "the fit")
    cur = result.get("current_season")
    if cur is None:
        current = ("Pending until enough gameweeks (about GW12): the current season has fewer "
                   "than 5 finished gameweeks with an FPL prediction so far.")
    else:
        current = (f"Season {cur['season']}, gameweeks {_ranges(cur['covered_gws'])} "
                   f"({len(cur['covered_gws'])} gameweeks), same rules as above. These are "
                   f"live numbers the parameters never saw.\n\n"
                   f"| Method | MAE | Rows |\n|---|---|---|\n{_table(cur, LABELS)}")
    text = f"""# Backtest report

Season: {result['season']}. Scoring starts at GW{result['from_gw']}.
Gameweeks scored ({len(covered)}): {ranges}. Rows scored: {result['model']['n']} per method.

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored.

**How forecast v2 was tested.** Its one fitted parameter (the attacking-points scale
factor `calib_att`, per position) was fitted on the {fit} season only
(`python -m fpl.fit`). It is scored here on {result['season']}, a season it never saw, so
its result is out of sample. The v2 DefCon and clean-sheet parts have no fitted parameters.

The past-season archive does not contain FPL's own predictions (`ep_pre`) for the other
gameweeks (listed as zero for every player, so stored as missing). Those gameweeks are
left out for all four methods, so every method is judged on exactly the same rows.
Gameweeks with no FPL prediction (between GW{result['from_gw']} and GW{result['last_gw']}): {_ranges(missing) or 'none'}.

| Method | MAE | Rows |
|---|---|---|
{_table(result, LABELS)}

## 3-gameweek check

Transfer suggestions use points over the next 3 gameweeks, so this table scores
those numbers too. Each start gameweek below has an FPL prediction and two more
gameweeks after it. Every method predicts the player's points summed over the
start gameweek and the next two, using only gameweeks before the start:

- SQL model v1 / Forecast v2: the model's expected points for the 3 gameweeks added up.
- Last-5 average × fixtures: the last-5 average times his number of fixtures.
- FPL ep_pre, scaled: FPL's prediction for the start gameweek, scaled by how many
  fixtures he has over the 3 gameweeks and how hard they are (what the app does).

Start gameweeks ({len(three['starts'])}): {_ranges(three['starts']) or 'none'}. Rows scored: {three['model']['n']} per method.
This sample is small, so read it as a sanity check as well as a decision input.

| Method | MAE | Rows |
|---|---|---|
{_table(three, LABELS3)}

## What the app uses

The app picks its source for each horizon separately. Forecast v2 is used for a horizon
only if its MAE is strictly lower than every other method's on identical rows; a tie
stays with the existing source.

- **Next gameweek:** {SOURCE_TEXT[s1]}. {_why(result, s1)}
- **Next 3 gameweeks:** {SOURCE_TEXT[s3]}{scaling}. {_why(three, s3)}

DefCon chance, clean-sheet chance, weaknesses and the last-6 stats are descriptive and
always shown, whichever source is chosen.

## Current season check

Does the choice above hold on the live season?

{current}

## Caveats

- **What was fitted where:** v1's fixture-difficulty (FDR) multipliers and v2's `calib_att`
  were both fitted on {fit} and are scored here on {result['season']}, a different season, so
  both results are out of sample. v1's MAE moved slightly from earlier reports (1.880 to 1.876,
  and FPL's 3-GW 3.630 to 3.635) because the fixture-difficulty multipliers are now fitted on
  the earlier season.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.
- The comparison covers only the gameweeks listed above, not the whole season.
"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--report", default="reports/backtest.md")
    ap.add_argument("--from-gw", type=int, default=6)
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    try:
        db.apply_views(conn)
        db.refresh_xp_cache(conn)
        season = conn.execute("SELECT value FROM meta WHERE key='backtest_season'").fetchone()[0]
        result = run(conn, season, args.from_gw)
        result["current_season"] = current_season_check(conn)
        write_report(result, Path(args.report))
        db.apply_views(conn)
        db.refresh_xp_cache(conn)
        conn.commit()
    finally:
        conn.close()
    for m in METHODS:
        print(f"{m}: MAE {result[m]['mae']:.3f} over {result[m]['n']} rows")
    print("sources: 1gw =", result["source_1gw"], " 3gw =", result["source_3gw"])
    for m in METHODS:
        t = result["three_gw"][m]
        print(f"3-GW {m}: MAE {t['mae']:.3f} over {t['n']} rows")


if __name__ == "__main__":
    main()
