"""Fit forecast v2's one free parameter: calib_att, per position.

    calib_att = sum(actual attacking points) / sum(predicted attacking points)

over meta.fit_season, gameweeks `from_gw` and later. Actual attacking points are
goals x GOAL_PTS + assists x 3 from player_gw_stats. The predicted side is
v_xp2_fixture.att_pred: the attacking term of forecast v2 with calib 1.0, so the
fit uses exactly the forecast's own formula (it is never re-implemented here).
Results are written to model_param; the backtest then scores them on a different
season (meta.backtest_season). A position with nothing predicted keeps 1.0.
"""
import argparse

from fpl import db

POSITIONS = ("GK", "DEF", "MID", "FWD")


def run(conn, from_gw: int = 6) -> dict:
    season = conn.execute("SELECT value FROM meta WHERE key = 'fit_season'").fetchone()[0]
    # predicted attacking points per player-gameweek, forecast made with as_of_gw = gw
    conn.execute("DROP TABLE IF EXISTS temp.fit_pred")
    conn.execute("""
        CREATE TEMP TABLE fit_pred AS
        SELECT player_id, gw, position, SUM(att_pred) AS pred
        FROM v_xp2_fixture
        WHERE season = ? AND as_of_gw = gw AND gw >= ?
          AND gw <= (SELECT MAX(gw) FROM player_gw WHERE season = ?)   -- loaded gameweeks only
        GROUP BY player_id, gw, position
    """, (season, from_gw, season))
    pred = {p: 0.0 for p in POSITIONS}
    actual = {p: 0.0 for p in POSITIONS}
    for pos, p_sum, a_sum in conn.execute("""
        SELECT f.position, SUM(f.pred),
               SUM(COALESCE(s.goals, 0) * CASE f.position WHEN 'MID' THEN 5 WHEN 'FWD' THEN 4
                                                         ELSE 6 END
                   + COALESCE(s.assists, 0) * 3)
        FROM fit_pred AS f
        LEFT JOIN player_gw_stats AS s
               ON s.season = ? AND s.player_id = f.player_id AND s.gw = f.gw
        GROUP BY f.position""", (season,)):
        pred[pos], actual[pos] = p_sum or 0.0, a_sum or 0.0
    conn.execute("DROP TABLE temp.fit_pred")
    calib = {p: (actual[p] / pred[p] if pred[p] > 0 else 1.0) for p in POSITIONS}
    for pos, value in calib.items():
        conn.execute("INSERT INTO model_param (name, position, value) VALUES ('calib_att', ?, ?) "
                     "ON CONFLICT(name, position) DO UPDATE SET value = excluded.value",
                     (pos, value))
    conn.commit()
    return calib


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--from-gw", type=int, default=6)
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    try:
        db.apply_views(conn)
        calib = run(conn, args.from_gw)
        db.refresh_xp_cache(conn)
    finally:
        conn.close()
    for pos, value in calib.items():
        print(f"calib_att {pos}: {value:.4f}")


if __name__ == "__main__":
    main()
