"""Backtest: do our SQL forecasts beat a simple baseline, and can FPL's number be trusted?

Archive tables. For every player-gameweek of the backtest season from `from_gw` on, three
one-gameweek-ahead predictions are scored against actual total_points (summed over a double
gameweek) by mean absolute error:

  model      v_xp.xp_model at as_of_gw = gw (uses only earlier gameweeks)
  v2         v_xp2.xp_v2 at as_of_gw = gw (forecast v2; calib_att fitted on
             meta.fit_season by fpl.fit, so scoring meta.backtest_season is out of sample)
  last5_avg  mean of the player's last 5 gameweek totals before gw

A row is scored only if the player was in a squad (minutes > 0 or v_player_form.start_prob
> 0) and all three predictions exist, so every method is judged on identical rows. Rows do
not need FPL's prediction (ep_pre): the archive's ep_pre was recorded after each gameweek
(see leak_check), so it is not scored here. That makes many more gameweeks scorable than
when rows needed ep_pre.

A second, 3-gameweek table (ruling R22) scores the numbers behind the transfer suggestions.
For each start gameweek g with g + 2 within the loaded season, each method predicts points
summed over g..g+2 using only gameweeks before g:

  model      sum of v_xp.xp_model over g..g+2 at as_of_gw = g
  v2         sum of v_xp2.xp_v2 over g..g+2 at as_of_gw = g
  last5_avg  last-5 average x number of fixtures in g..g+2

choose_source picks the app's source per horizon (meta.forecast_source_1gw / _3gw, and
meta.forecast_source = the 1-gameweek choice for compatibility): the lowest MAE of model, v2
and last5_avg; ties go to the model, then v2. FPL's number is never a source.

leak_check(conn, season) tests whether an archive season's ep_pre saw the result: it compares
ep_pre with the player's 4-gameweek points average including that gameweek and with the 4
gameweeks before it, and looks at ep_pre for 12+ point scores against the week before.

fpl_fair_check(conn) is the only place FPL's prediction is scored: current season, one
gameweek ahead, on rows whose ep_pre was saved before that gameweek's deadline (fpl.collect
stores ep_pre only then). Under 5 such gameweeks the verdict is "too early to call".
"""
import argparse
from pathlib import Path

from fpl import db

METHODS = ("model", "last5_avg", "v2")
# the fair check adds FPL's own prediction; this order breaks ties (model, v2, last-5, FPL)
FAIR_METHODS = ("model", "v2", "last5_avg", "fpl_ep")
MIN_FAIR_GWS = 5
TOO_EARLY = "too early to call"
LABELS = {"model": "SQL model v1 (v_xp)", "last5_avg": "Last-5 average",
          "fpl_ep": "FPL's prediction, saved before kick-off", "v2": "Forecast v2 (v_xp2)"}
LABELS3 = {"model": "SQL model v1 (v_xp), summed over 3 GWs",
           "v2": "Forecast v2 (v_xp2), summed over 3 GWs",
           "last5_avg": "Last-5 average × fixtures"}


def _best(table: dict, order) -> str | None:
    """Lowest-MAE method in `order` with scored rows; ties go to the earlier one."""
    valid = [m for m in order if m in table and table[m]["n"] > 0]
    return min(valid, key=lambda m: table[m]["mae"]) if valid else None


def choose_source(table: dict) -> str:
    """Lowest MAE of model / v2 / last5_avg (ties go to the model, then v2); 'model' if none
    has rows. FPL's number is never returned, even if the table holds it."""
    return _best(table, ("model", "v2", "last5_avg")) or "model"


def _score_one_gw(conn, season: str, from_gw: int, with_fpl: bool = False) -> dict:
    """1-gameweek table for `season`. Leaves temp.bt_actual / bt_xp / bt_v2 for _three_gw;
    the caller drops them with _drop_temp. with_fpl also scores ep_pre as 'fpl_ep' and keeps
    only rows that have it (the fair check); otherwise ep_pre is ignored."""
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
          AND a.actual IS NOT NULL
          AND x.xp_model IS NOT NULL AND v.xp1 IS NOT NULL
    """)
    where = "last5_avg IS NOT NULL" + (" AND fpl_ep IS NOT NULL" if with_fpl else "")
    result = {}
    for m in FAIR_METHODS if with_fpl else METHODS:
        mae, n = conn.execute(
            f"SELECT AVG(ABS({m} - actual)), COUNT(*) FROM bt_scored WHERE {where}").fetchone()
        result[m] = {"mae": float(mae) if mae is not None else float("nan"), "n": int(n)}
    gws = conn.execute(f"SELECT MIN(gw), MAX(gw) FROM bt_scored WHERE {where}").fetchone()
    covered = [g for (g,) in conn.execute(
        f"SELECT DISTINCT gw FROM bt_scored WHERE {where} ORDER BY gw")]
    players = conn.execute(
        f"SELECT COUNT(DISTINCT player_id) FROM bt_scored WHERE {where}").fetchone()[0]
    conn.execute("DROP TABLE temp.bt_scored")
    result.update(season=season, from_gw=from_gw, first_gw=gws[0], last_gw=gws[1],
                  covered_gws=covered, players=players)
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
    result["winner"] = result["source_1gw"]
    _set_meta(conn, "forecast_source_1gw", result["source_1gw"])
    _set_meta(conn, "forecast_source_3gw", result["source_3gw"])
    _set_meta(conn, "forecast_source", result["source_1gw"])      # kept for compatibility
    conn.commit()
    return result


def leak_check(conn, season: str) -> dict:
    """Did `season`'s archived ep_pre see the result? Per player-gameweek he played (minutes >
    0, double gameweeks summed) with an ep_pre: MAE of ep_pre against his average points over
    the gameweeks he played in g-3..g (incl, includes the week) and in g-4..g-1 (excl, the
    weeks before), on rows where both averages exist. A genuine forecast can only know the
    weeks before, so mae_incl < mae_excl points to a number recorded after the gameweek.
    big_*: mean ep_pre in the week of a 12+ point score and in the week before, for scores
    with an ep_pre the week before."""
    conn.execute("DROP TABLE IF EXISTS temp.lk_gw")
    # ep_pre is identical on both rows of a double gameweek in the archive, so MAX() picks it
    conn.execute("""
        CREATE TEMP TABLE lk_gw AS
        SELECT player_id, gw, SUM(minutes) AS minutes, SUM(total_points) AS pts,
               MAX(ep_pre) AS ep
        FROM player_gw WHERE season = ? GROUP BY player_id, gw
    """, (season,))
    conn.execute("CREATE INDEX temp.lk_gw_i ON lk_gw (player_id, gw)")
    mae_incl, mae_excl, n = conn.execute("""
        WITH s AS (
            SELECT a.ep,
                   (SELECT AVG(b.pts) FROM lk_gw AS b WHERE b.player_id = a.player_id
                      AND b.minutes > 0 AND b.gw BETWEEN a.gw - 3 AND a.gw) AS incl,
                   (SELECT AVG(b.pts) FROM lk_gw AS b WHERE b.player_id = a.player_id
                      AND b.minutes > 0 AND b.gw BETWEEN a.gw - 4 AND a.gw - 1) AS excl
            FROM lk_gw AS a WHERE a.minutes > 0 AND a.ep IS NOT NULL)
        SELECT AVG(ABS(ep - incl)), AVG(ABS(ep - excl)), COUNT(*)
        FROM s WHERE incl IS NOT NULL AND excl IS NOT NULL
    """).fetchone()
    big_week, big_before, n_big = conn.execute("""
        SELECT AVG(a.ep), AVG(p.ep), COUNT(*)
        FROM lk_gw AS a JOIN lk_gw AS p ON p.player_id = a.player_id AND p.gw = a.gw - 1
        WHERE a.minutes > 0 AND a.ep IS NOT NULL AND a.pts >= 12 AND p.ep IS NOT NULL
    """).fetchone()
    conn.execute("DROP TABLE temp.lk_gw")
    nan = float("nan")
    return {"mae_incl": nan if mae_incl is None else float(mae_incl),
            "mae_excl": nan if mae_excl is None else float(mae_excl), "n": int(n),
            "big_ep_week": nan if big_week is None else float(big_week),
            "big_ep_before": nan if big_before is None else float(big_before),
            "n_big": int(n_big)}


def archive_seasons(conn) -> list[str]:
    """Loaded seasons other than the current one, oldest first."""
    cur = conn.execute("SELECT value FROM meta WHERE key = 'current_season'").fetchone()
    return [s for (s,) in conn.execute(
        "SELECT DISTINCT season FROM player_gw WHERE season IS NOT ? ORDER BY season",
        (cur[0] if cur else None,))]


def fpl_fair_check(conn) -> dict:
    """FPL's prediction against ours, fairly: current season, one gameweek ahead, only rows
    whose ep_pre was saved before that gameweek's deadline (fpl.collect keeps no other), all
    four methods on identical rows. excluded_gws: loaded gameweeks with no saved prediction.
    The verdict is the lowest-MAE method, or "too early to call" under MIN_FAIR_GWS
    gameweeks."""
    season = conn.execute("SELECT value FROM meta WHERE key = 'current_season'").fetchone()[0]
    excluded = [g for (g,) in conn.execute(
        "SELECT gw FROM player_gw WHERE season = ? GROUP BY gw HAVING COUNT(ep_pre) = 0 "
        "ORDER BY gw", (season,))]
    first = conn.execute("SELECT MIN(gw) FROM player_gw WHERE season = ? AND ep_pre IS NOT NULL",
                         (season,)).fetchone()[0]
    if first is None:
        methods = {m: {"mae": float("nan"), "n": 0} for m in FAIR_METHODS}
        gws, players = [], 0
    else:
        r = _score_one_gw(conn, season, first, with_fpl=True)
        _drop_temp(conn)
        methods = {m: r[m] for m in FAIR_METHODS}
        gws, players = r["covered_gws"], r["players"]
    verdict = (_best(methods, FAIR_METHODS) if len(gws) >= MIN_FAIR_GWS else None) or TOO_EARLY
    return {"season": season, "methods": methods, "gws": gws, "players": players,
            "excluded_gws": excluded, "verdict": verdict}


def _three_gw(conn, season: str, from_gw: int) -> dict:
    """3-gameweek check (R22). Reads temp.bt_actual, bt_xp and bt_v2 from _score_one_gw()."""
    # model total and fixture count over g..g+2, forecast at as_of g
    conn.execute("""
        CREATE TEMP TABLE bt_xp3 AS
        SELECT player_id, as_of_gw AS gw,
               SUM(xp) AS xp3,
               SUM(fixture_id IS NOT NULL) AS fixtures3
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
               t.fixtures3 * (SELECT AVG(p.actual) FROM (
                    SELECT actual FROM bt_actual
                    WHERE player_id = a.player_id AND gw < a.gw
                    ORDER BY gw DESC LIMIT 5) AS p) AS last5_avg
        FROM bt_actual AS a
        JOIN bt_xp AS x ON x.player_id = a.player_id AND x.gw = a.gw
        JOIN bt_xp3 AS t ON t.player_id = a.player_id AND t.gw = a.gw
        JOIN bt_v2 AS v ON v.player_id = a.player_id AND v.gw = a.gw
        WHERE (a.minutes > 0 OR x.start_prob > 0)
          AND t.xp3 IS NOT NULL AND v.xp3 IS NOT NULL
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
    "model": "our v1 SQL model",
    "v2": "forecast v2 (built from xG, xA, clean-sheet chance and DefCon chance)",
    "last5_avg": "the player's last-5 average",
}


def _table(result_part: dict, labels: dict, methods=METHODS) -> str:
    return "\n".join(
        f"| {labels[m]} | {result_part[m]['mae']:.3f} | {result_part[m]['n']} |" for m in methods)


def _why(table: dict, source: str) -> str:
    """One sentence on why `source` was chosen for a horizon."""
    if source not in table or table[source]["n"] == 0:
        return "No rows could be scored, so the default is kept."
    others = [m for m in METHODS if m != source and table[m]["n"] > 0]
    if not others:
        return f"It was the only method with scored rows (MAE {table[source]['mae']:.3f})."
    nxt = min(others, key=lambda m: table[m]["mae"])
    rel = "level with" if table[nxt]["mae"] == table[source]["mae"] else "below"
    return (f"{LABELS[source]} had the lowest MAE ({table[source]['mae']:.3f}), {rel} the next "
            f"best ({LABELS[nxt]}, {table[nxt]['mae']:.3f}).")


def _leak_text(leak: dict) -> str:
    if not leak:
        return "Not run for this report."
    out = []
    for season, r in leak.items():
        if r["n"] == 0:
            out.append(f"**{season}.** The archive has no FPL predictions for this season, "
                       f"so there is nothing to check.")
            continue
        closer = r["mae_incl"] < r["mae_excl"]
        para = (f"**{season}.** Over {r['n']} player-gameweeks, FPL's archived prediction was "
                f"{'closer to' if closer else 'further from'} the player's points average over "
                f"the 4 gameweeks *including* that week (error {r['mae_incl']:.3f}) than to the "
                f"average over the 4 gameweeks *before* it (error {r['mae_excl']:.3f}). A "
                f"prediction made before kick-off can only know the weeks before.")
        if r["n_big"]:
            jump = r["big_ep_week"] > r["big_ep_before"]
            para += (f" When a player scored 12 or more ({r['n_big']} times), FPL's number for "
                     f"that week averaged {r['big_ep_week']:.2f}, against "
                     f"{r['big_ep_before']:.2f} the week before"
                     f"{': it rose with the result.' if jump else '.'}")
        para += (" Both point to a number recorded after the gameweek."
                 if closer and r["n_big"] and r["big_ep_week"] > r["big_ep_before"] else
                 " This is no clear sign of a leak." if not closer else "")
        out.append(para)
    return "\n\n".join(out)


def _fair_text(fair: dict | None) -> str:
    if fair is None:
        return "Not run for this report."
    gws, excl = fair["gws"], fair["excluded_gws"]
    left_out = (f"Gameweeks left out, with no FPL prediction saved before the deadline: "
                f"{_ranges(excl)}." if excl else "No loaded gameweek was left out.")
    if not gws:
        return (f"Season {fair['season']}: no gameweek has an FPL prediction saved before "
                f"kick-off yet, so the verdict is {TOO_EARLY}.\n\n{left_out}")
    verdict = (f"Verdict: {TOO_EARLY}. This is a small, growing sample: under {MIN_FAIR_GWS} "
               f"gameweeks, so read it as an early sign, not proof."
               if fair["verdict"] == TOO_EARLY else
               f"Verdict: {LABELS[fair['verdict']]} has the lowest error so far. This is "
               f"still a small, growing sample.")
    return f"""Season {fair['season']}, one gameweek ahead. FPL's prediction is scored only where our
collector saved it before that gameweek's deadline, so it could not have seen the result.
Every method is scored on the same rows.

Gameweeks ({len(gws)}): {_ranges(gws)}. Players: {fair['players']}. Rows: {fair['methods']['fpl_ep']['n']} per method.
{left_out}

| Method | MAE | Rows |
|---|---|---|
{_table(fair['methods'], LABELS, FAIR_METHODS)}

{verdict}"""


def write_report(result: dict, path: Path) -> None:
    three = result["three_gw"]
    covered = result["covered_gws"]
    ranges = _ranges(covered)
    missing = [g for g in range(result["from_gw"], (result["last_gw"] or 0) + 1)
               if g not in covered]
    s1, s3 = result["source_1gw"], result["source_3gw"]
    fit = result.get("fit_season", "the fit")
    gaps = (f"\nGameweeks with no scored rows (between GW{result['from_gw']} and "
            f"GW{result['last_gw']}): {_ranges(missing)}." if missing else "")
    text = f"""# Backtest report

Season: {result['season']}. Scoring starts at GW{result['from_gw']}.
Gameweeks scored ({len(covered)}): {ranges}. Rows scored: {result['model']['n']} per method.{gaps}

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored.

**How forecast v2 was tested.** Its one fitted parameter (the attacking-points scale
factor `calib_att`, per position) was fitted on the {fit} season only
(`python -m fpl.fit`). It is scored here on {result['season']}, a season it never saw, so
its result is out of sample. The v2 DefCon and clean-sheet parts have no fitted parameters.

**Why FPL's prediction is not in these tables.** The past-season archive's FPL prediction
(`ep_pre`) was recorded after each gameweek, so it had seen the result (see "Leak check"
below). It is no longer scored here, and rows no longer need it. That means many more
gameweeks are scored than in earlier reports, which only used the few gameweeks with an
archived FPL prediction, so the numbers are not comparable with those reports. FPL's
prediction is compared fairly in "FPL's prediction, saved before kick-off" below.

| Method | MAE | Rows |
|---|---|---|
{_table(result, LABELS)}

## 3-gameweek check

Transfer suggestions use points over the next 3 gameweeks, so this table scores
those numbers too. Each start gameweek below has two more gameweeks after it. Every
method predicts the player's points summed over the start gameweek and the next two,
using only gameweeks before the start:

- SQL model v1 / Forecast v2: the model's expected points for the 3 gameweeks added up.
- Last-5 average × fixtures: the last-5 average times his number of fixtures.

Start gameweeks ({len(three['starts'])}): {_ranges(three['starts']) or 'none'}. Rows scored: {three['model']['n']} per method.

| Method | MAE | Rows |
|---|---|---|
{_table(three, LABELS3)}

## What the app uses

The app picks its source for each horizon separately: the method with the lowest MAE on
identical rows. A tie goes to the SQL model, then forecast v2. FPL's number is never used.

- **Next gameweek:** {SOURCE_TEXT[s1]}. {_why(result, s1)}
- **Next 3 gameweeks:** {SOURCE_TEXT[s3]}. {_why(three, s3)}

DefCon chance, clean-sheet chance, weaknesses and the last-6 stats are descriptive and
always shown, whichever source is chosen.

## Leak check

Was the archive's FPL prediction made before the gameweek, or recorded after it? Two tests,
recomputed from the database on every run. Only gameweeks the player played are counted,
and a double gameweek's points are added up.

{_leak_text(result.get('leak'))}

## FPL's prediction, saved before kick-off

{_fair_text(result.get('fair'))}

## Caveats

- **What was fitted where:** v1's fixture-difficulty (FDR) multipliers and v2's `calib_att`
  were both fitted on {fit} and are scored here on {result['season']}, a different season, so
  both results are out of sample.
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
        result["leak"] = {s: leak_check(conn, s) for s in archive_seasons(conn)}
        result["fair"] = fpl_fair_check(conn)
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
    for s, r in result["leak"].items():
        print(f"leak {s}: mae_incl {r['mae_incl']:.3f} mae_excl {r['mae_excl']:.3f} n {r['n']}; "
              f"12+ ep {r['big_ep_week']:.2f} vs {r['big_ep_before']:.2f} (n {r['n_big']})")
    f = result["fair"]
    print(f"fair check: gws {f['gws']} excluded {f['excluded_gws']} verdict {f['verdict']}")


if __name__ == "__main__":
    main()
