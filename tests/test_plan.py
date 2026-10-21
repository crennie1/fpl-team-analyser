import pytest

from fpl.analyse import Analysis
from fpl.plan import (Move, add, apply_action, build, changes, extra_hit, hit, summary, undo_last,
                      undo_original)
from fpl.squad import SquadError
from fpl.suggest import HIT_COST
from tests.test_suggest import add_player, bench_case, make_user


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


def test_undo_refuses_when_later_promotion_loses_its_starter(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    a, bench = pids[5], pids[13]
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    add_player(db_with_squads, 7002, "MID", 301, 5.0)
    m = add(base, [], a, 7001, db_with_squads)                          # B=7001 starts
    m = add(base, m, bench, 7002, db_with_squads, promote_over=7001)
    before = list(m)
    with pytest.raises(SquadError, match="not in your squad"):
        undo_original(base, m, a, db_with_squads)
    assert m == before


def _analysis(grades, p3, gw=7):
    return Analysis([], grades, 0.0, 0.0, gw, None, projected3=p3)


def test_summary_none_without_changes(db_with_squads, add_squad):
    base, _ = setup(db_with_squads, add_squad)
    a = _analysis({"midfield": "B"}, 30.0)
    assert summary(base, base, a, a, {}, {}, 1) is None


def test_summary_hits_and_only_changed_grades(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    add_player(db_with_squads, 7002, "FWD", 301, 5.0)
    m = add(base, [], pids[5], 7001, db_with_squads)
    m = add(base, m, pids[10], 7002, db_with_squads)
    cur = build(base, m, db_with_squads)
    real = _analysis({"midfield": "B", "attack": "C", "projected": "x"}, 30.0)
    plan_a = _analysis({"midfield": "A", "attack": "C", "projected": "y"}, 36.0)
    names = {pids[5]: "Out1", pids[10]: "Out2", 7001: "In1", 7002: "In2"}
    prices = {pids[5]: 5.04, pids[10]: 6.0, 7001: 5.5, 7002: 5.0}
    s = summary(base, cur, real, plan_a, names, prices, 1)
    assert s["n_changes"] == 2 and s["ft_used"] == 1
    assert s["hit"] == 4 and s["compare"]["pts3_after_hits"][1] == pytest.approx(plan_a.projected3 - 4)
    assert s["compare"]["pts3_after_hits"][0] == pytest.approx(30.0)
    assert s["compare"]["pts3"] == [30.0, 36.0]
    assert s["compare"]["grades"] == [["midfield", "B", "A"]]
    assert all(b != a for _, b, a in s["compare"]["grades"])
    assert s["compare"]["bank"] == [round(base.bank / 10, 1), round(cur.bank / 10, 1)]
    assert s["bank"] == round(cur.bank / 10, 1)
    c = s["changes"][0]
    assert (c["out_id"], c["out_name"], c["in_id"], c["in_name"]) == (pids[5], "Out1", 7001, "In1")
    assert (c["out_price"], c["in_price"], c["diff"]) == (5.0, 5.5, 0.5)


def fresh_state(ft=1):
    return {"team": "1", "moves": [], "ft": ft, "last_n": 0, "error": None, "focus_id": None}


def test_apply_action_ignores_replayed_n(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    act = {"type": "swap", "out_id": pids[5], "in_id": 7001, "n": 3}
    s = apply_action(fresh_state(), act, base, db_with_squads)
    s = apply_action(s, act, base, db_with_squads)
    s = apply_action(s, {"type": "reset", "n": 2}, base, db_with_squads)   # older: ignored
    assert s["moves"] == [Move(pids[5], 7001)] and s["last_n"] == 3
    assert s["focus_id"] == 7001 and s["error"] is None


def test_apply_action_swap_error_kept_plan_unchanged(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    # club 200 holds pids[0] and pids[8]; a third makes it full
    db_with_squads.execute("UPDATE player SET team_id = 200 WHERE player_id = ?", (pids[1],))
    db_with_squads.commit()
    add_player(db_with_squads, 7001, "MID", 200, 5.0)
    add_player(db_with_squads, 7002, "FWD", 300, 5.0)
    s = apply_action(fresh_state(), {"type": "swap", "out_id": pids[10], "in_id": 7002, "n": 1},
                     base, db_with_squads)
    before = s["moves"]
    s = apply_action(s, {"type": "swap", "out_id": pids[5], "in_id": 7001, "n": 2},
                     base, db_with_squads)
    assert "Too many players from one club" in s["error"]
    assert s["moves"] == before and s["last_n"] == 2
    s = apply_action(s, {"type": "undo_last", "n": 3}, base, db_with_squads)
    assert s["moves"] == [] and s["error"] is None                 # next action clears it


def test_apply_action_bench_option_promotes(db_with_squads, add_squad):
    squad, pids, weak, bench = bench_case(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 12.0, cost=90, xp_next=5.0)   # a 👍: starts
    add_player(db_with_squads, 7002, "MID", 301, 30.0, cost=90, xp_next=1.0)   # would not start
    s = apply_action(fresh_state(), {"type": "swap", "out_id": bench, "in_id": 7001, "n": 1},
                     squad, db_with_squads)
    assert s["moves"] == [Move(bench, 7001, promote_over=weak)]
    by_id = {p.player_id: p for p in build(squad, s["moves"], db_with_squads).picks}
    assert by_id[7001].is_starter and not by_id[weak].is_starter
    s = apply_action(fresh_state(), {"type": "swap", "out_id": bench, "in_id": 7002, "n": 1},
                     squad, db_with_squads)
    assert s["moves"] == [Move(bench, 7002)]                       # not a 👍: stays on the bench


def test_apply_action_set_ft_bounds(db_with_squads, add_squad):
    base, _ = setup(db_with_squads, add_squad)
    s = apply_action(fresh_state(), {"type": "set_ft", "ft": 9, "n": 1}, base, db_with_squads)
    assert s["ft"] == 5
    s = apply_action(s, {"type": "set_ft", "ft": -2, "n": 2}, base, db_with_squads)
    assert s["ft"] == 0
    s = apply_action(s, {"type": "set_ft", "ft": 2, "n": 3}, base, db_with_squads)
    assert s["ft"] == 2


def test_apply_action_undo_and_reset(db_with_squads, add_squad):
    base, pids = setup(db_with_squads, add_squad)
    add_player(db_with_squads, 7001, "MID", 300, 5.0)
    add_player(db_with_squads, 7002, "FWD", 301, 5.0)
    s = fresh_state()
    for n, (o, i) in enumerate(((pids[5], 7001), (pids[10], 7002)), start=1):
        s = apply_action(s, {"type": "swap", "out_id": o, "in_id": i, "n": n}, base, db_with_squads)
    s2 = apply_action(s, {"type": "undo", "original_id": pids[5], "n": 3}, base, db_with_squads)
    assert s2["moves"] == [Move(pids[10], 7002)]
    s2 = apply_action(s, {"type": "undo_last", "n": 3}, base, db_with_squads)
    assert s2["moves"] == [Move(pids[5], 7001)]
    s2 = apply_action(s, {"type": "reset", "n": 3}, base, db_with_squads)
    assert s2["moves"] == [] and s2["ft"] == 1
    assert s["moves"] == [Move(pids[5], 7001), Move(pids[10], 7002)]   # input not changed
