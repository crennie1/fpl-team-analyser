"""Collect the current season from the official FPL API into SQLite."""
import argparse
from datetime import datetime, timedelta, timezone

from fpl import db
from fpl.api import FplClient

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


COMMIT_WINDOW = timedelta(hours=48)
REFERENCE_WEEKDAY = 1          # Tuesday (datetime.weekday: Monday = 0)


def _utcnow():
    return datetime.now(timezone.utc)


def should_commit(new_gw: bool, next_deadline: str | None, now: datetime,
                  manual: bool = False) -> bool:
    """Should the daily workflow commit data/fpl.db? (ruling V8)

    Yes when (a) a new gameweek was loaded, (b) the next gameweek's deadline is within
    48 hours (keeps the last pre-deadline snapshot of FPL's predictions), or (c) it is the
    Tuesday reference run (a manual run also refreshes the reference sample). Otherwise
    the run changes nothing in git, so the repository does not grow by a full copy a day.
    """
    if new_gw or manual or now.weekday() == REFERENCE_WEEKDAY:
        return True
    if not next_deadline:
        return False
    deadline = datetime.fromisoformat(next_deadline.replace("Z", "+00:00"))
    return timedelta(0) <= deadline - now <= COMMIT_WINDOW


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
            "INSERT OR REPLACE INTO player (season, player_id, web_name, team_id, position,"
            " first_name, second_name) VALUES (?,?,?,?,?,?,?)",
            (season, e["id"], e["web_name"], e["team"], POSITIONS[e["element_type"]],
             e.get("first_name"), e.get("second_name")),
        )
    for f in fixtures:
        conn.execute(
            "INSERT OR REPLACE INTO fixture VALUES (?,?,?,?,?,?,?,?)",
            (season, f["id"], f["event"], f["team_h"], f["team_a"],
             f["team_h_difficulty"], f["team_a_difficulty"], int(bool(f["finished"]))),
        )


def _set_pieces(conn, season, boot, collected_at):
    """Replace the season's set-piece duties with the bootstrap's current ones."""
    conn.execute("DELETE FROM set_piece WHERE season = ?", (season,))
    for e in boot["elements"]:
        pen = e.get("penalties_order")
        cor = e.get("corners_and_indirect_freekicks_order")
        fk = e.get("direct_freekicks_order")
        if pen is None and cor is None and fk is None:
            continue
        conn.execute(
            "INSERT INTO set_piece (season, player_id, penalties_order, corners_order,"
            " direct_fk_order, collected_at) VALUES (?,?,?,?,?,?)",
            (season, e["id"], pen, cor, fk, collected_at))


def _flt(v):
    return None if v in (None, "") else float(v)


def _parse_utc(text):
    """Parse an ISO-8601 time ("...Z" or with offset) to an aware datetime; None if missing or bad."""
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _store_deadlines(conn, season, boot):
    for e in boot["events"]:
        if e.get("deadline_time"):
            conn.execute(
                "INSERT OR REPLACE INTO gw_deadline (season, gw, deadline_time) VALUES (?,?,?)",
                (season, e["id"], e["deadline_time"]))


def _snapshot(conn, season, boot, next_gw, collected_at):
    if next_gw is None:
        return
    # A run after the deadline (FPL can still list that gameweek as next) must not replace a
    # row taken before it: only pre-deadline predictions count in the fair check.
    row = conn.execute(
        "SELECT deadline_time FROM gw_deadline WHERE season = ? AND gw = ?", (season, next_gw)).fetchone()
    deadline = _parse_utc(row[0]) if row else None
    keep = set()
    taken_now = _parse_utc(collected_at)
    if deadline and taken_now and taken_now >= deadline:
        for r in conn.execute(
                "SELECT player_id, collected_at FROM player_snapshot WHERE season = ? AND gw = ?",
                (season, next_gw)):
            taken = _parse_utc(r[1])
            if taken and taken < deadline:
                keep.add(r[0])
    for e in boot["elements"]:
        if e["id"] in keep:
            continue
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
    # FPL's prediction counts only if it was collected before the deadline; later ones saw the matches.
    row = conn.execute(
        "SELECT deadline_time FROM gw_deadline WHERE season = ? AND gw = ?", (season, gw)).fetchone()
    deadline = _parse_utc(row[0]) if row else None
    ep = {}
    for r in conn.execute(
            "SELECT player_id, ep_next, collected_at FROM player_snapshot WHERE season = ? AND gw = ?",
            (season, gw)):
        taken = _parse_utc(r["collected_at"])
        if deadline and taken and taken < deadline:
            ep[r["player_id"]] = r["ep_next"]
    team_of = {
        r["player_id"]: r["team_id"]
        for r in conn.execute("SELECT player_id, team_id FROM player WHERE season = ?", (season,))
    }
    team_pos = {
        r["player_id"]: r["position"]
        for r in conn.execute("SELECT player_id, position FROM player WHERE season = ?", (season,))
    }
    n = 0
    for el in client.event_live(gw)["elements"]:
        pid = el["id"]
        if pid not in team_of:
            continue
        apps = hits = 0
        matched = False
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
            matched = True
            apps += minutes > 0
            hits += any(s["identifier"] == "defensive_contribution" and s["points"] > 0
                        for s in stats)
        if matched:
            st = el.get("stats", {})
            conn.execute(
                "INSERT OR REPLACE INTO player_gw_stats (season, gw, player_id, minutes, starts,"
                " xg, xa, xgi, xgc, goals, assists, clean_sheets, goals_conceded,"
                " defcon_actions, defcon_hits, apps) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (season, gw, pid, st.get("minutes"), st.get("starts"),
                 _flt(st.get("expected_goals")), _flt(st.get("expected_assists")),
                 _flt(st.get("expected_goal_involvements")),
                 _flt(st.get("expected_goals_conceded")),
                 st.get("goals_scored"), st.get("assists"), st.get("clean_sheets"),
                 st.get("goals_conceded"), st.get("defensive_contribution"),
                 0 if team_pos[pid] == "GK" else hits, apps))
    return n


def season_from_bootstrap(boot) -> str:
    """Season label from the first gameweek's deadline: year Y gives "Y-(Y+1)", e.g. 2026-27."""
    year = int(boot["events"][0]["deadline_time"][:4])
    return f"{year}-{(year + 1) % 100:02d}"


def run(conn, client, season=None):
    """Collect bootstrap, fixtures and new finished gameweeks; return player_gw rows upserted.

    With no season given, it is derived from the bootstrap (season_from_bootstrap).
    """
    boot = client.bootstrap()
    season = season or season_from_bootstrap(boot)
    fixtures = client.fixtures()
    collected_at = _now()
    next_event = next((e for e in boot["events"] if e["is_next"]), None)
    next_gw = next_event["id"] if next_event else None

    _upsert_static(conn, season, boot, fixtures)
    _store_deadlines(conn, season, boot)
    _snapshot(conn, season, boot, next_gw, collected_at)
    _set_pieces(conn, season, boot, collected_at)

    # Keyed on player_gw_stats so gameweeks collected before v2 get their stats backfilled.
    have = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT gw FROM player_gw_stats WHERE season = ?", (season,))
    }
    rows = 0
    for e in boot["events"]:
        if e["finished"] and e["id"] not in have:
            rows += _load_live(conn, client, season, e["id"])

    if next_gw is not None:
        _set_meta(conn, "next_gw", next_gw)
        if next_event.get("deadline_time"):
            _set_meta(conn, "next_deadline", next_event["deadline_time"])
    _set_meta(conn, "last_collected", collected_at)
    _set_meta(conn, "current_season", season)
    conn.commit()
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/fpl.db")
    p.add_argument("--season", help="e.g. 2026-27; default: derived from the FPL API")
    p.add_argument("--should-commit", action="store_true",
                   help="collect nothing; print true/false: should the workflow commit the db (V8)")
    p.add_argument("--new-gw", action="store_true", help="with --should-commit: a new gameweek was loaded")
    p.add_argument("--manual", action="store_true", help="with --should-commit: a manual run")
    args = p.parse_args(argv)
    if args.should_commit:
        conn = db.connect(args.db)
        row = conn.execute("SELECT value FROM meta WHERE key = 'next_deadline'").fetchone()
        conn.close()
        ok = should_commit(args.new_gw, row[0] if row else None, _utcnow(), args.manual)
        print("true" if ok else "false")
        return
    from pathlib import Path
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)
    db.apply_sql(conn, "schema.sql")
    n = run(conn, FplClient(), args.season)
    db.apply_views(conn)
    db.refresh_xp_cache(conn)
    print(f"Upserted {n} player-gameweek rows")
    conn.close()


if __name__ == "__main__":
    main()
