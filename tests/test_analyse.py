import pytest

from fpl.analyse import analyse_squad
from fpl.squad import Pick, Squad


def metrics(conn, squad_id="user"):
    return conn.execute("SELECT * FROM v_squad_metrics WHERE squad_id = ?", (squad_id,)).fetchone()


def grades(conn):
    return {r["area"]: r["grade"] for r in
            conn.execute("SELECT area, grade FROM v_squad_grades WHERE squad_id = 'user'")}


def squad_of(pids, captain_slot=9):
    picks = [Pick(pid, slot, slot <= 11, slot == captain_slot, 50)
             for slot, pid in enumerate(pids, start=1)]
    return Squad(1, 5, picks, 0, 1)


def test_projected_doubles_captain(db_with_squads, add_squad):
    add_squad(db_with_squads, "user", 9000, xp=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 0, 0, 0],
              captain_slot=9)
    # starters 1..11 sum to 66, captain (slot 9, xp 9) counts again
    assert metrics(db_with_squads)["projected"] == pytest.approx(66 + 9)


def test_bench_excluded_from_projection(db_with_squads, add_squad):
    add_squad(db_with_squads, "user", 9000, xp=[2] * 11 + [50] * 4)
    m = metrics(db_with_squads)
    assert m["projected"] == pytest.approx(22 + 2)   # 11 starters + captain again
    assert m["bench"] == pytest.approx(200)


def test_grade_best_squad_gets_A(db_with_squads, add_squad):
    add_squad(db_with_squads, "user", 9000, xp=20.0)   # refs top out at 7 per player
    g = grades(db_with_squads)
    assert g["attack"] == "A" and g["projected"] == "A"


def test_fixtures_grade_inverted(db_with_squads, add_squad):
    add_squad(db_with_squads, "user", 9000, team=5)    # easy fixtures, FDR 2 vs refs' 3
    assert metrics(db_with_squads)["fixtures"] == pytest.approx(2.0)
    assert grades(db_with_squads)["fixtures"] == "A"


def test_fixtures_hard_squad_graded_E(db_with_squads, add_squad):
    add_squad(db_with_squads, "user", 9000, team=6)    # FDR 5, worse than every ref
    assert grades(db_with_squads)["fixtures"] == "E"


def test_risk_counts_flagged_starter(db_with_squads, add_squad):
    # slot 2 is injured with xp 5; the other 10 starters have 4.5 each: 5 / 50 = 0.1
    xp = [4.5] * 15
    xp[1] = 5
    add_squad(db_with_squads, "user", 9000, xp=xp, flags={2: ("i", 0)})
    assert metrics(db_with_squads)["risk"] == pytest.approx(0.1)


def test_risk_ignores_flagged_bench_player(db_with_squads, add_squad):
    add_squad(db_with_squads, "user", 9000, flags={13: ("i", 0)})
    assert metrics(db_with_squads)["risk"] == pytest.approx(0.0)


def test_colour_rules(db_with_squads, add_squad):
    xp = [6.0] * 15
    xp[0], xp[1], xp[2], xp[3] = 1.5, 3.0, 6.0, 6.0
    pids = add_squad(db_with_squads, "user", 9000, xp=xp, flags={4: ("d", 25)})
    result = analyse_squad(db_with_squads, squad_of(pids))
    colours = [p.colour for p in result.players[:4]]
    assert colours == ["red", "amber", "green", "red"]
    assert result.players[3].flag == "News 9004"      # FPL's news text for status != 'a'
    assert result.players[2].flag is None


def test_average_projected_is_ref_mean(db_with_squads, add_squad):
    pids = add_squad(db_with_squads, "user", 9000)
    result = analyse_squad(db_with_squads, squad_of(pids))
    # ref k: 12 counted players at (2 + k) -> 12 * 5 on average
    assert result.average_projected == pytest.approx(60.0)
    assert result.projected == pytest.approx(48.0)
    assert set(result.grades) == {"attack", "midfield", "defence", "fixtures", "risk", "bench", "projected"}


def test_analyse_replaces_existing_user_squad(db_with_squads, add_squad):
    first = add_squad(db_with_squads, "user", 9000)
    other = add_squad(db_with_squads, "spare", 9500, xp=1.0)
    analyse_squad(db_with_squads, squad_of(first))
    analyse_squad(db_with_squads, squad_of(other))
    n = db_with_squads.execute("SELECT COUNT(*) FROM squad_pick WHERE squad_id = 'user'").fetchone()[0]
    assert n == 15
    assert metrics(db_with_squads)["bench"] == pytest.approx(4.0)


def test_no_reference_squads_gives_dash_grades(db_with_squads, add_squad):
    db_with_squads.execute("DELETE FROM reference_squad")
    pids = add_squad(db_with_squads, "user", 9000)
    result = analyse_squad(db_with_squads, squad_of(pids))
    assert set(result.grades.values()) == {"–"}
    assert result.average_projected == 0.0


def test_xp_cache_matches_v_xp_next_after_refresh(db_with_squads):
    from fpl import db
    conn = db_with_squads
    conn.execute("UPDATE player_snapshot SET ep_next = 9.9 WHERE player_id = 1")
    db.refresh_xp_cache(conn)
    cache = [tuple(r) for r in conn.execute("SELECT * FROM xp_next_cache ORDER BY player_id")]
    live = [tuple(r) for r in conn.execute("SELECT * FROM v_xp_next ORDER BY player_id")]
    assert cache == live and len(cache) > 0
    assert conn.execute("SELECT xp_next FROM xp_next_cache WHERE player_id = 1").fetchone()[0] == 9.9


def test_player_missing_from_db_is_named_not_dropped_silently(db_with_squads, add_squad):
    pids = add_squad(db_with_squads, "user", 9000)
    pids[14] = 99999                      # bench FWD the collector hasn't loaded yet
    a = analyse_squad(db_with_squads, squad_of(pids))
    assert a.missing == [99999]
    assert len(a.players) == 14
    assert analyse_squad(db_with_squads, squad_of(pids[:14] + [9015])).missing == []
