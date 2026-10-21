import pytest

from fpl.plan import Move, add, build, changes, extra_hit, hit, undo_last, undo_original
from fpl.squad import SquadError
from fpl.suggest import HIT_COST
from tests.test_suggest import add_player, make_user


def setup(conn, add_squad, ft=1):
    squad, pids = make_user(conn, add_squad, ft=ft)
    return squad, pids


def pick(squad, pid):
    return next(p for p in squad.picks if p.player_id == pid)


def test_no_moves_is_base(db_with_squads, add_squad):
    base, _ = setup(db_with_squads, add_squad)
    assert build(base, [], db_with_squads) == base and changes(base, base) == []


def test_swap_back_to_original_cancels_change(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    a, b = pids[5], 7001
    add_player(db_with_squads, b, "MID", 300, 5.0)
    m = add(base, [], a, b, db_with_squads)
    m = add(base, m, b, a, db_with_squads)
    assert changes(base, build(base, m, db_with_squads)) == []


def test_chain_counts_once_and_undo_restores_original(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    a = pids[5]
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    add_player(db_with_squads, 7002, "MID", 301, 5.0)
    m = add(base, add(base, [], a, 7001, db_with_squads), 7001, 7002, db_with_squads)
    assert changes(base, build(base, m, db_with_squads)) == [(a, 7002)]
    assert undo_original(base, m, a, db_with_squads) == []


def test_changes_in_squad_order(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    add_player(db_with_squads, 7002, "FWD", 301, 5.0)
    m = add(base, [], pids[10], 7002, db_with_squads)
    m = add(base, m, pids[5], 7001, db_with_squads)
    assert changes(base, build(base, m, db_with_squads)) == [(pids[5], 7001), (pids[10], 7002)]


def test_undo_refuses_when_rule_breaks(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    for i in (1, 2, 3):                              # three DEF at one club: full
        db_with_squads.execute("UPDATE player SET team_id = 250 WHERE player_id = ?", (pids[i],))
    db_with_squads.commit()
    add_player(db_with_squads, 7001, "DEF", 301, 5.0)
    add_player(db_with_squads, 7002, "DEF", 250, 5.0)
    m = add(base, [], pids[1], 7001, db_with_squads)         # frees a slot at club 250
    m = add(base, m, pids[4], 7002, db_with_squads)          # fills it
    before = list(m)
    with pytest.raises(SquadError, match="Too many players from one club"):
        undo_original(base, m, pids[1], db_with_squads)
    assert m == before


def test_add_refuses_rule_break(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "FWD", 300, 5.0)
    with pytest.raises(SquadError):
        add(base, [], pids[5], 7001, db_with_squads)         # MID for FWD


def test_over_budget_allowed(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 5.0, cost=140)
    cur = build(base, add(base, [], pids[5], 7001, db_with_squads), db_with_squads)
    assert cur.bank < 0


def test_promotion_and_undo_restore_slots_exactly(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    bench_mid, weak = pids[13], pids[5]
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    m = add(base, [], bench_mid, 7001, db_with_squads, promote_over=weak)
    cur = build(base, m, db_with_squads)
    assert pick(cur, 7001).is_starter and not pick(cur, weak).is_starter
    assert changes(base, cur) == [(bench_mid, 7001)]
    assert build(base, undo_original(base, m, bench_mid, db_with_squads), db_with_squads) == base


def test_hits():
    assert hit(2, 1) == HIT_COST and hit(1, 1) == 0 and hit(3, 0) == 12 and hit(0, 2) == 0


def test_extra_hit(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    add_player(db_with_squads, 7002, "MID", 301, 5.0)
    cur = build(base, add(base, [], pids[5], 7001, db_with_squads), db_with_squads)
    assert extra_hit(base, cur, 7001, 7002, 0) == 0           # replaces an IN player
    assert extra_hit(base, cur, pids[6], 7002, 0) == HIT_COST  # a new slot costs a hit
    assert extra_hit(base, cur, pids[6], 7002, 2) == 0        # still free


def test_undo_last():
    m1, m2 = Move(1, 2), Move(3, 4)
    assert undo_last([m1, m2]) == [m1] and undo_last([]) == []
