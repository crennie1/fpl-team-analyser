from fpl import db

V1_DDL = """
CREATE TABLE team (season TEXT NOT NULL, team_id INTEGER NOT NULL, name TEXT NOT NULL,
    short_name TEXT NOT NULL, PRIMARY KEY (season, team_id));
CREATE TABLE player (season TEXT NOT NULL, player_id INTEGER NOT NULL, web_name TEXT NOT NULL,
    team_id INTEGER NOT NULL, position TEXT NOT NULL, PRIMARY KEY (season, player_id));
CREATE TABLE player_snapshot (season TEXT NOT NULL, gw INTEGER NOT NULL, player_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL, status TEXT, chance_next INTEGER, ep_next REAL, now_cost INTEGER,
    selected_by_percent REAL, PRIMARY KEY (season, gw, player_id));
CREATE TABLE player_gw (season TEXT NOT NULL, gw INTEGER NOT NULL, player_id INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL, minutes INTEGER, total_points INTEGER, was_home INTEGER,
    opponent_team INTEGER, fdr INTEGER, ep_pre REAL, PRIMARY KEY (season, gw, player_id, fixture_id));
INSERT INTO player VALUES ('2025-26', 7, 'Old', 1, 'MID');
INSERT INTO player_gw VALUES ('2025-26', 3, 7, 11, 90, 5, 1, 2, 3, 4.2);
"""


def test_migrate_v1_db(tmp_path):
    conn = db.connect(tmp_path / "v1.db")
    conn.executescript(V1_DDL)
    db.apply_sql(conn, "schema.sql")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"player_gw_stats", "set_piece"} <= tables
    assert {"first_name", "second_name"} <= {r[1] for r in conn.execute("PRAGMA table_info(player)")}
    assert "news" in {r[1] for r in conn.execute("PRAGMA table_info(player_snapshot)")}
    row = conn.execute("SELECT * FROM player_gw").fetchone()
    assert (row["player_id"], row["minutes"], row["ep_pre"]) == (7, 90, 4.2)
    p = conn.execute("SELECT * FROM player").fetchone()
    assert p["web_name"] == "Old" and p["first_name"] is None
    db.apply_sql(conn, "schema.sql")   # second run is a no-op
