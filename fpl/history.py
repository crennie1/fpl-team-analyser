"""Load a past season from the vaastav Fantasy-Premier-League archive."""
import argparse
import csv
import tempfile
from pathlib import Path

import requests

from fpl import db

RAW = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
POSITIONS = {"GKP": "GK", "GK": "GK", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
USER_AGENT = "fpl-team-analyser (personal project)"


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _int(v):
    return int(v) if v not in (None, "") else None


def _float(v):
    return float(v) if v not in (None, "") else None


def _bool(v):
    return 1 if str(v).strip().lower() in ("true", "1") else 0


def load(conn, season, merged_gw_csv, fixtures_csv, teams_csv):
    """Replace `season` in team/player/fixture/player_gw; return player_gw row count."""
    teams = _rows(teams_csv)
    fixtures = _rows(fixtures_csv)
    merged = _rows(merged_gw_csv)

    team_by_name = {t["name"]: int(t["id"]) for t in teams}
    fix_by_id = {int(f["id"]): f for f in fixtures}

    # Player attributes: take the latest gameweek row (handles mid-season transfers).
    latest = {}
    for r in sorted(merged, key=lambda r: int(r["GW"])):
        latest[int(r["element"])] = r

    with conn:
        for table in ("player_gw", "fixture", "player", "team"):
            conn.execute(f"DELETE FROM {table} WHERE season = ?", (season,))

        conn.executemany(
            "INSERT INTO team (season, team_id, name, short_name) VALUES (?,?,?,?)",
            [(season, int(t["id"]), t["name"], t["short_name"]) for t in teams],
        )
        conn.executemany(
            "INSERT INTO player (season, player_id, web_name, team_id, position)"
            " VALUES (?,?,?,?,?)",
            [
                (season, pid, r["name"], team_by_name[r["team"]], POSITIONS[r["position"]])
                for pid, r in latest.items()
            ],
        )
        conn.executemany(
            "INSERT INTO fixture (season, fixture_id, gw, team_h, team_a,"
            " team_h_difficulty, team_a_difficulty, finished) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    season, int(f["id"]), _int(f["event"]), int(f["team_h"]), int(f["team_a"]),
                    _int(f["team_h_difficulty"]), _int(f["team_a_difficulty"]),
                    _bool(f["finished"]),
                )
                for f in fixtures
            ],
        )

        rows = []
        for r in merged:
            fid = int(r["fixture"])
            home = _bool(r["was_home"])
            fx = fix_by_id.get(fid)
            fdr = None
            if fx:
                fdr = _int(fx["team_h_difficulty" if home else "team_a_difficulty"])
            rows.append((
                season, int(r["GW"]), int(r["element"]), fid, _int(r["minutes"]),
                _int(r["total_points"]), home, _int(r["opponent_team"]), fdr, _float(r["xP"]),
            ))
        # OR IGNORE: the archive repeats some rows verbatim (players who changed club).
        conn.executemany(
            "INSERT OR IGNORE INTO player_gw (season, gw, player_id, fixture_id, minutes,"
            " total_points, was_home, opponent_team, fdr, ep_pre) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('backtest_season', ?)", (season,)
        )
        return conn.execute(
            "SELECT COUNT(*) FROM player_gw WHERE season = ?", (season,)
        ).fetchone()[0]


def _download(url, dest):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    Path(dest).write_bytes(resp.content)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--season", required=True, help="e.g. 2025-26")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base = f"{RAW}/{args.season}"
        paths = {
            "merged": tmp / "merged_gw.csv",
            "fixtures": tmp / "fixtures.csv",
            "teams": tmp / "teams.csv",
        }
        _download(f"{base}/gws/merged_gw.csv", paths["merged"])
        _download(f"{base}/fixtures.csv", paths["fixtures"])
        _download(f"{base}/teams.csv", paths["teams"])

        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        conn = db.connect(args.db)
        try:
            db.apply_sql(conn, "schema.sql")
            n = load(conn, args.season, paths["merged"], paths["fixtures"], paths["teams"])
            db.apply_views(conn)
        finally:
            conn.close()
    print(f"loaded {n} player_gw rows for {args.season}")


if __name__ == "__main__":
    main()
