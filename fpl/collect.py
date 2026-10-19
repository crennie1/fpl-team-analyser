"""Collect the current season from the official FPL API into SQLite."""
import argparse
from datetime import datetime, timezone

from fpl import db
from fpl.api import FplClient

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _upsert_static(conn, season, boot, fixtures):
    for t in boot["teams"]:
        conn.execute(
            "INSERT OR REPLACE INTO team VALUES (?,?,?,?)",
            (season, t["id"], t["name"], t["short_name"]),
        )
    for e in boot["elements"]:
        conn.execute(
            "INSERT OR REPLACE INTO player VALUES (?,?,?,?,?)",
            (season, e["id"], e["web_name"], e["team"], POSITIONS[e["element_type"]]),
        )
    for f in fixtures:
        conn.execute(
            "INSERT OR REPLACE INTO fixture VALUES (?,?,?,?,?,?,?,?)",
            (season, f["id"], f["event"], f["team_h"], f["team_a"],
             f["team_h_difficulty"], f["team_a_difficulty"], int(bool(f["finished"]))),
        )


def _snapshot(conn, season, boot, next_gw, collected_at):
    if next_gw is None:
        return
    for e in boot["elements"]:
        conn.execute(
            "INSERT OR REPLACE INTO player_snapshot (season, gw, player_id, collected_at, "
            "status, chance_next, ep_next, now_cost, selected_by_percent, news) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (season, next_gw, e["id"], collected_at, e["status"],
             e["chance_of_playing_next_round"],
             None if e["ep_next"] is None else float(e["ep_next"]),
             e["now_cost"], float(e["selected_by_percent"]), e.get("news") or None),
        )


def _load_live(conn, client, season, gw):
    """Insert player_gw rows for one finished gameweek; return the count."""
    fixtures = {
        r["fixture_id"]: r
        for r in conn.execute(
            "SELECT * FROM fixture WHERE season = ? AND gw = ?", (season, gw))
    }
    ep = {
        r["player_id"]: r["ep_next"]
        for r in conn.execute(
            "SELECT player_id, ep_next FROM player_snapshot WHERE season = ? AND gw = ?",
            (season, gw))
    }
    team_of = {
        r["player_id"]: r["team_id"]
        for r in conn.execute("SELECT player_id, team_id FROM player WHERE season = ?", (season,))
    }
    n = 0
    for el in client.event_live(gw)["elements"]:
        pid = el["id"]
        if pid not in team_of:
            continue
        for ex in el.get("explain", []):
            fx = fixtures.get(ex["fixture"])
            if fx is None:
                continue
            stats = ex.get("stats", [])
            minutes = sum(s["value"] for s in stats if s["identifier"] == "minutes")
            points = sum(s["points"] for s in stats)
            home = team_of[pid] == fx["team_h"]
            conn.execute(
                "INSERT OR REPLACE INTO player_gw VALUES (?,?,?,?,?,?,?,?,?,?)",
                (season, gw, pid, fx["fixture_id"], minutes, points, int(home),
                 fx["team_a"] if home else fx["team_h"],
                 fx["team_h_difficulty"] if home else fx["team_a_difficulty"],
                 ep.get(pid)),
            )
            n += 1
    return n


def run(conn, client, season):
    """Collect bootstrap, fixtures and new finished gameweeks; return player_gw rows upserted."""
    boot = client.bootstrap()
    fixtures = client.fixtures()
    collected_at = _now()
    next_gw = next((e["id"] for e in boot["events"] if e["is_next"]), None)

    _upsert_static(conn, season, boot, fixtures)
    _snapshot(conn, season, boot, next_gw, collected_at)

    have = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT gw FROM player_gw WHERE season = ?", (season,))
    }
    rows = 0
    for e in boot["events"]:
        if e["finished"] and e["id"] not in have:
            rows += _load_live(conn, client, season, e["id"])

    if next_gw is not None:
        _set_meta(conn, "next_gw", next_gw)
    _set_meta(conn, "last_collected", collected_at)
    _set_meta(conn, "current_season", season)
    conn.commit()
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/fpl.db")
    p.add_argument("--season", required=True)
    args = p.parse_args(argv)
    from pathlib import Path
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)
    db.apply_sql(conn, "schema.sql")
    n = run(conn, FplClient(), args.season)
    db.apply_views(conn)
    print(f"Upserted {n} player-gameweek rows")
    conn.close()


if __name__ == "__main__":
    main()
