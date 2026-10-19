from fpl import collect, db


def count(conn, table):
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def test_collect_loads_players_and_positions(tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    assert {r["position"] for r in tmp_db.execute("select position from player")} == {"GK", "DEF", "MID", "FWD"}
    assert count(tmp_db, "team") == 3
    assert count(tmp_db, "fixture") == 4


def test_collect_player_gw_has_fdr_from_player_side(tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    fx = tmp_db.execute("select * from fixture where fixture_id = 1").fetchone()
    for r in tmp_db.execute(
        "select p.team_id, g.* from player_gw g join player p using (season, player_id) where g.fixture_id = 1"
    ):
        if r["team_id"] == fx["team_h"]:
            assert r["was_home"] == 1 and r["fdr"] == fx["team_h_difficulty"]
            assert r["opponent_team"] == fx["team_a"]
        else:
            assert r["was_home"] == 0 and r["fdr"] == fx["team_a_difficulty"]
            assert r["opponent_team"] == fx["team_h"]


def test_collect_is_idempotent(tmp_db, fake_client):
    first = collect.run(tmp_db, fake_client, "2026-27")
    assert first == 6
    before = {t: count(tmp_db, t) for t in ("team", "player", "fixture", "player_gw", "player_snapshot")}
    second = collect.run(tmp_db, fake_client, "2026-27")
    assert second == 0
    assert fake_client.live_calls == [1]
    assert before == {t: count(tmp_db, t) for t in before}


def test_collect_sets_meta(tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    meta = {r["key"]: r["value"] for r in tmp_db.execute("select * from meta")}
    assert meta["next_gw"] == "2"
    assert meta["current_season"] == "2026-27"
    assert meta["last_collected"].endswith("+00:00")


def test_snapshot_ep_copied_to_player_gw_ep_pre(tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    snap = tmp_db.execute("select player_id, ep_next from player_snapshot where gw = 2").fetchall()
    assert len(snap) == 6
    assert tmp_db.execute("select count(*) from player_gw where ep_pre is not null").fetchone()[0] == 0
    # a snapshot taken before gw1 is copied onto that gameweek's rows
    tmp_db.execute("delete from player_gw")
    tmp_db.execute(
        "insert into player_snapshot (season, gw, player_id, collected_at, status, chance_next, ep_next, now_cost, selected_by_percent) values ('2026-27',1,?, 'x','a',100,7.5,100,1.0)", (snap[0]["player_id"],))
    collect.run(tmp_db, fake_client, "2026-27")
    row = tmp_db.execute(
        "select ep_pre from player_gw where player_id = ?", (snap[0]["player_id"],)).fetchone()
    assert row["ep_pre"] == 7.5


def test_apply_views_skips_missing_and_memory_copy(tmp_path, tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    db.apply_views(tmp_db)
    tmp_db.close()
    mem = db.memory_copy(tmp_path / "test.db")
    assert count(mem, "player") == 6


def test_collect_double_gw_two_rows(tmp_db, fake_client):
    # Turn GW1 into a double gameweek for the first player: add a second GW1 fixture
    # (team 1 away at team 5, other difficulties) and a second explain entry.
    base_fixtures = fake_client.fixtures()
    base_live = fake_client.event_live(1)
    team = fake_client.bootstrap()["elements"][0]["team"]
    pid = fake_client.bootstrap()["elements"][0]["id"]
    other = next(t["id"] for t in fake_client.bootstrap()["teams"] if t["id"] != team)
    extra = {"id": 900, "event": 1, "team_h": other, "team_a": team,
             "team_h_difficulty": 4, "team_a_difficulty": 2, "finished": True}
    for el in base_live["elements"]:
        if el["id"] == pid:
            el["explain"].append({"fixture": 900, "stats": [
                {"identifier": "minutes", "points": 1, "value": 30, "points_modification": 0},
                {"identifier": "goals_scored", "points": 6, "value": 1, "points_modification": 0}]})
    fake_client.fixtures = lambda: base_fixtures + [extra]
    fake_client.event_live = lambda gw: base_live

    collect.run(tmp_db, fake_client, "2026-27")
    rows = tmp_db.execute(
        "select * from player_gw where player_id = ? order by fixture_id", (pid,)).fetchall()
    assert len(rows) == 2
    first, second = rows
    assert first["fixture_id"] == 1 and first["minutes"] == 90 and first["total_points"] == 6
    assert second["fixture_id"] == 900 and second["minutes"] == 30 and second["total_points"] == 7
    assert second["was_home"] == 0 and second["fdr"] == 2 and second["opponent_team"] == other


def test_snapshot_stores_news_text(tmp_db, fake_client):
    collect.run(tmp_db, fake_client, "2026-27")
    rows = dict(tmp_db.execute("select player_id, news from player_snapshot").fetchall())
    assert rows[8] == "Knee injury - 25% chance of playing"
    assert rows[1] is None  # empty news is stored as NULL


def test_migrate_adds_news_to_old_database(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE player_snapshot (season TEXT, gw INTEGER, player_id INTEGER)")
    db.apply_sql(conn, "schema.sql")
    assert "news" in {r[1] for r in conn.execute("PRAGMA table_info(player_snapshot)")}


def test_season_from_bootstrap_first_deadline_year():
    assert collect.season_from_bootstrap({"events": [{"deadline_time": "2026-08-21T17:30:00Z"}]}) == "2026-27"
    assert collect.season_from_bootstrap({"events": [{"deadline_time": "2099-08-15T10:00:00Z"}]}) == "2099-00"
    assert collect.season_from_bootstrap({"events": [{"deadline_time": "2030-08-09T17:30:00Z"}]}) == "2030-31"


def test_collect_derives_season_when_omitted(tmp_db, fake_client):
    collect.run(tmp_db, fake_client)
    assert tmp_db.execute("select value from meta where key='current_season'").fetchone()[0] == "2026-27"
    assert tmp_db.execute("select count(distinct season) from player").fetchone()[0] == 1
