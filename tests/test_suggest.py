import pytest

from fpl.analyse import analyse_squad
from fpl.db import refresh_xp_cache
from fpl.squad import Pick, Squad
from fpl.suggest import suggest


def set_xp3(conn, pid, xp3):
    conn.execute("UPDATE xp_next_cache SET xp_next3 = ? WHERE player_id = ?", (xp3, pid))
    conn.commit()


def make_user(conn, add_squad, ft=1, bank=0, xp=4.0):
    """User squad 9001..9015 spread over 8 clubs (max 2 each); selling price 50 each."""
    pids = add_squad(conn, "user", 9000, xp=xp)
    for i, pid in enumerate(pids):
        conn.execute("UPDATE player SET team_id = ? WHERE player_id = ?", (200 + i % 8, pid))
    conn.commit()
    refresh_xp_cache(conn)
    picks = [Pick(pid, s, s <= 11, s == 9, 50) for s, pid in enumerate(pids, start=1)]
    return Squad(1, 5, picks, bank, ft), pids


def add_player(conn, pid, position, team, xp3, cost=50):
    conn.execute("INSERT INTO player (season, player_id, web_name, team_id, position) "
                 "VALUES ('2026-27', ?, ?, ?, ?)", (pid, f"N{pid}", team, position))
    conn.execute("INSERT INTO player_snapshot (season, gw, player_id, collected_at, status, "
                 "chance_next, ep_next, now_cost, selected_by_percent) "
                 "VALUES ('2026-27', 6, ?, '2026-10-19T12:00:00', 'a', NULL, 4.0, ?, 1.0)",
                 (pid, cost))
    conn.execute("INSERT INTO xp_next_cache (player_id, xp_next, xp_next3, start_prob, xp_source) "
                 "VALUES (?, 4.0, ?, 1.0, 'test')", (pid, xp3))
    conn.commit()


def base(db_with_squads, add_squad, **kw):
    squad, pids = make_user(db_with_squads, add_squad, **kw)
    db_with_squads.execute("UPDATE xp_next_cache SET xp_next3 = 0")   # nobody else is a target
    for pid in pids:
        set_xp3(db_with_squads, pid, 12.0)
    return squad, pids


def test_suggests_replacing_injured_player(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad)
    mid = pids[5]                       # slot 6, MID
    set_xp3(db_with_squads, mid, 0.0)
    add_player(db_with_squads, 7001, "MID", 300, 12.0)
    s = suggest(db_with_squads, squad)
    assert s[0].out_id == mid and s[0].in_id == 7001
    assert s[0].gain3 == pytest.approx(12.0) and s[0].hit == 0
    assert s[0].grade_change[0] == "midfield"


def test_respects_budget(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad)
    set_xp3(db_with_squads, pids[5], 0.0)
    add_player(db_with_squads, 7001, "MID", 300, 20.0, cost=90)    # unaffordable
    add_player(db_with_squads, 7002, "MID", 301, 10.0, cost=50)
    assert suggest(db_with_squads, squad)[0].in_id == 7002
    squad.bank = 40                                                # now 90 fits
    assert suggest(db_with_squads, squad)[0].in_id == 7001


def test_respects_three_per_club(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad)
    set_xp3(db_with_squads, pids[5], 0.0)
    for pid in (pids[0], pids[1], pids[2]):
        db_with_squads.execute("UPDATE player SET team_id = 250 WHERE player_id = ?", (pid,))
    db_with_squads.commit()
    add_player(db_with_squads, 7001, "MID", 250, 30.0)     # club full
    add_player(db_with_squads, 7002, "MID", 301, 10.0)
    assert suggest(db_with_squads, squad)[0].in_id == 7002


def test_hit_applied_when_no_free_transfers(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad, ft=0)
    set_xp3(db_with_squads, pids[5], 0.0)
    add_player(db_with_squads, 7001, "MID", 300, 12.0)
    s = suggest(db_with_squads, squad)[0]
    assert s.hit == 4 and s.net_gain3 == pytest.approx(s.gain3 - 4) == pytest.approx(8.0)


def test_no_suggestion_when_gain_small(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 12.4)     # gain 0.4 < 0.5
    assert suggest(db_with_squads, squad) == []
    squad.free_transfers = 0
    add_player(db_with_squads, 7002, "MID", 301, 16.3)     # gain 4.3, net 0.3 after the hit
    assert suggest(db_with_squads, squad) == []


def test_distinct_out_players(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad)
    set_xp3(db_with_squads, pids[5], 0.0)
    set_xp3(db_with_squads, pids[6], 1.0)
    add_player(db_with_squads, 7001, "MID", 300, 20.0)
    add_player(db_with_squads, 7002, "MID", 301, 19.0)
    s = suggest(db_with_squads, squad, k=3)
    assert [x.out_id for x in s][:2] == [pids[5], pids[6]]
    assert len({x.out_id for x in s}) == len(s)
    assert len({x.in_id for x in s}) == len(s)
    assert [x.in_id for x in s][:2] == [7001, 7002]


def test_leaves_original_squad_stored(db_with_squads, add_squad):
    squad, pids = base(db_with_squads, add_squad)
    set_xp3(db_with_squads, pids[5], 0.0)
    add_player(db_with_squads, 7001, "MID", 300, 12.0)
    assert suggest(db_with_squads, squad)
    stored = {r[0] for r in db_with_squads.execute(
        "SELECT player_id FROM squad_pick WHERE squad_id = 'user'")}
    assert stored == set(pids)

