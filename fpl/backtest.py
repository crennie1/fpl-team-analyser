"""Backtest: does the SQL forecast beat two simple baselines?

For every player-gameweek from `from_gw` on, three one-gameweek-ahead
predictions are scored against actual total_points (summed over a double
gameweek) by mean absolute error:

  model      v_xp.xp_model at as_of_gw = gw (uses only earlier gameweeks)
  last5_avg  mean of the player's last 5 gameweek totals before gw
  fpl_ep     FPL's own pre-gameweek ep_pre

A row is scored only if the player was in a squad (minutes > 0 or
v_player_form.start_prob > 0) and ALL three predictions exist, so every
method is judged on identical rows.
"""
import argparse
from pathlib import Path

from fpl import db

METHODS = ("model", "last5_avg", "fpl_ep")
LABELS = {"model": "SQL model (v_xp)", "last5_avg": "Last-5 average", "fpl_ep": "FPL ep_pre"}


def run(conn, season: str, from_gw: int = 6) -> dict:
    # Intermediate results live in TEMP tables so the heavy views run once.
    conn.executescript("""
        DROP TABLE IF EXISTS temp.bt_actual;
        DROP TABLE IF EXISTS temp.bt_xp;
        DROP TABLE IF EXISTS temp.bt_scored;
    """)
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
    # last5_avg: mean of up to 5 most recent earlier gameweek totals;
    # players with no earlier gameweek have no baseline and are dropped.
    conn.execute("""
        CREATE TEMP TABLE bt_scored AS
        SELECT a.player_id, a.gw, a.actual, x.xp_model AS model, a.ep_pre AS fpl_ep,
               (SELECT AVG(p.actual) FROM (
                    SELECT actual FROM bt_actual
                    WHERE player_id = a.player_id AND gw < a.gw
                    ORDER BY gw DESC LIMIT 5) AS p) AS last5_avg
        FROM bt_actual AS a
        JOIN bt_xp AS x ON x.player_id = a.player_id AND x.gw = a.gw
        WHERE (a.minutes > 0 OR x.start_prob > 0)
          AND a.ep_pre IS NOT NULL AND a.actual IS NOT NULL AND x.xp_model IS NOT NULL
    """)
    where = "last5_avg IS NOT NULL"
    result = {}
    for m in METHODS:
        mae, n = conn.execute(
            f"SELECT AVG(ABS({m} - actual)), COUNT(*) FROM bt_scored WHERE {where}").fetchone()
        result[m] = {"mae": float(mae) if mae is not None else float("nan"), "n": int(n)}
    gws = conn.execute(f"SELECT MIN(gw), MAX(gw) FROM bt_scored WHERE {where}").fetchone()
    conn.executescript("DROP TABLE temp.bt_scored; DROP TABLE temp.bt_xp; DROP TABLE temp.bt_actual;")

    valid = {m: result[m]["mae"] for m in METHODS if result[m]["n"] > 0}
    # Ties go to "model" first (listed first): the cheaper, explainable choice.
    winner = min(valid, key=valid.get) if valid else "model"
    result.update(winner=winner, season=season, from_gw=from_gw,
                  first_gw=gws[0], last_gw=gws[1])
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 ("fpl_ep" if winner == "fpl_ep" else "model",))
    conn.commit()
    return result


def write_report(result: dict, path: Path) -> None:
    w = result["winner"]
    if w == "fpl_ep":
        meaning = ("The app will show FPL's own `ep_next` as its expected points, "
                   "because it predicted better than our model.")
    elif w == "model":
        meaning = ("The app will use our SQL model for expected points, because it "
                   "predicted better than both baselines.")
    else:
        meaning = ("The app will use our SQL model for expected points; the simple "
                   "last-5 average was closest, so the model adds little over plain form.")
    base = min(result["last5_avg"]["mae"], result["fpl_ep"]["mae"])
    verdict = "beat" if result["model"]["mae"] < base else "did not beat"
    rows = "\n".join(
        f"| {LABELS[m]} | {result[m]['mae']:.3f} | {result[m]['n']} |" for m in METHODS)
    text = f"""# Backtest report

Season: {result['season']}, gameweeks {result['first_gw']} to {result['last_gw']} \
(scoring starts at GW{result['from_gw']}).

Each method predicts one gameweek ahead using only earlier information. Score is mean
absolute error (MAE) in FPL points per player-gameweek; lower is better. Only players
who were in a squad (minutes > 0 or start probability > 0) are scored, and only rows
where all three methods have a prediction, so every method is judged on the same rows.

| Method | MAE | Rows |
|---|---|---|
{rows}

Winner: **{LABELS[w]}**. The model {verdict} the better baseline.

What this means for the app: {meaning}

## Caveats

- **In-sample caveat:** the fixture-difficulty (FDR) multipliers in the model were fit
  on this same season ({result['season']}), so the model's MAE here is slightly
  optimistic. The baselines have no such advantage.
- A player's first appearance has no last-5 history, so those rows are dropped for all methods.
- Double gameweeks: actual points and predictions are summed over both fixtures.
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
        season = conn.execute("SELECT value FROM meta WHERE key='backtest_season'").fetchone()[0]
        result = run(conn, season, args.from_gw)
        write_report(result, Path(args.report))
        db.apply_views(conn)
        conn.commit()
    finally:
        conn.close()
    for m in METHODS:
        print(f"{m}: MAE {result[m]['mae']:.3f} over {result[m]['n']} rows")
    print("winner:", result["winner"])


if __name__ == "__main__":
    main()
