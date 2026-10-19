import pytest

from fpl import db
from fpl.api import FplApiError
from fpl.squad import (Pick, Squad, SquadError, estimate_free_transfers, load_squad,
                       selling_price, swap, validate)

SEASON = "2026-27"
POS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
# ids: GK 1,2; DEF 3-7; MID 8-12; FWD 13-15; teams spread so no club exceeds 3.
# Starters: 1,3,4,5,6,8,9,10,11,13,14.


@pytest.fixture
def conn(tmp_db):
    c = tmp_db
    c.execute("INSERT INTO meta VALUES ('current_season', ?)", (SEASON,))
    for i, pos in enumerate(POS, start=1):
        c.execute("INSERT INTO player VALUES (?,?,?,?,?)", (SEASON, i, f"P{i}", (i % 8) + 1, pos))
        c.execute("INSERT INTO player_snapshot (season, gw, player_id, collected_at, status, chance_next, ep_next, now_cost, selected_by_percent) VALUES (?,?,?,?,?,?,?,?,?)",
                  (SEASON, 9, i, "2026-10-19T12:00:00", "a", None, 1.0, 50, 5.0))
    # extra candidates: 20 GK, 21 DEF (team 1), 22 MID cheap, 23 MID pricey
    for pid, pos, team, cost in [(20, "GK", 9, 40), (21, "DEF", 1, 50), (22, "MID", 9, 50),
                                 (23, "MID", 9, 150)]:
        c.execute("INSERT INTO player VALUES (?,?,?,?,?)", (SEASON, pid, f"P{pid}", team, pos))
        c.execute("INSERT INTO player_snapshot (season, gw, player_id, collected_at, status, chance_next, ep_next, now_cost, selected_by_percent) VALUES (?,?,?,?,?,?,?,?,?)",
                  (SEASON, 9, pid, "2026-10-19T12:00:00", "a", None, 1.0, cost, 5.0))
    c.commit()
    db.apply_views(c)
    return c


def make_squad(conn, bank=0):
    starters = {1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14}
    picks = [Pick(i, i, i in starters, i == 9, 50) for i in range(1, 16)]
    return Squad(1, 9, picks, bank, 1, None)


class FakeEntryClient:
    def __init__(self, current_event=9, chip=None, bank=15, transfers=(), history=None,
                 status=None, banks=None, elements=()):
        self.banks = banks or {}
        self.elements = list(elements)
        self.bootstrap_calls = 0
        self.current_event = current_event
        self.chip = chip
        self.bank = bank
        self._transfers = list(transfers)
        self._history = history or {"current": [{"event": 1, "event_transfers": 0}], "chips": []}
        self.status = status
        self.picks_calls = []
        self.summary_calls = []

    def entry(self, tid):
        if self.status:
            raise FplApiError("nope", status=self.status)
        return {"current_event": self.current_event, "name": "T"}

    def entry_picks(self, tid, gw):
        self.picks_calls.append(gw)
        chip = self.chip if gw == self.current_event else None
        return {"active_chip": chip, "entry_history": {"bank": self.banks.get(gw, self.bank), "value": 1000},
                "picks": [{"element": i, "position": i, "multiplier": 1,
                           "is_captain": i == 9, "is_vice_captain": i == 10}
                          for i in range(1, 16)]}

    def entry_history(self, tid):
        return self._history

    def entry_transfers(self, tid):
        return self._transfers

    def element_summary(self, pid):
        self.summary_calls.append(pid)
        return {"history": [{"round": 1, "value": 50}]}

    def bootstrap(self):
        self.bootstrap_calls += 1
        return {"elements": self.elements}


def test_load_squad_unknown_id(conn):
    with pytest.raises(SquadError, match="No FPL team found with ID 99999999"):
        load_squad(FakeEntryClient(status=404), conn, 99999999)


def test_load_squad_non_numeric(conn):
    with pytest.raises(SquadError, match="Team ID must be a number"):
        load_squad(FakeEntryClient(), conn, "abc")


def test_load_squad_preseason(conn):
    with pytest.raises(SquadError, match="Season hasn't started — no squad to analyse yet"):
        load_squad(FakeEntryClient(current_event=None), conn, 1)


def test_load_squad_basic(conn):
    sq = load_squad(FakeEntryClient(), conn, "123")
    assert sq.team_id == 123 and sq.gw == 9 and sq.bank == 15 and sq.note is None
    assert [p.slot for p in sq.picks] == list(range(1, 16))
    assert sum(p.is_starter for p in sq.picks) == 11
    assert [p.player_id for p in sq.picks if p.is_captain] == [9]


def test_free_hit_uses_previous_picks(conn):
    t = [{"element_in": 12, "element_in_cost": 30, "element_out": 99, "element_out_cost": 30,
          "event": 9, "time": "2026-10-18T10:00:00Z"}]
    client = FakeEntryClient(current_event=9, chip="freehit", transfers=t, banks={9: 5, 8: 23})
    sq = load_squad(client, conn, 1)
    assert client.picks_calls == [9, 8]
    assert sq.gw == 8
    assert "Free Hit" in sq.note and "GW8" in sq.note
    assert sq.bank == 23
    # the Free Hit week transfer-in must not set player 12's buy price (fallback: 50)
    assert next(p for p in sq.picks if p.player_id == 12).selling_price == 50


def test_selling_price_rule():
    assert selling_price(80, 83) == 81
    assert selling_price(80, 85) == 82
    assert selling_price(80, 78) == 78


def test_selling_price_from_transfers(conn):
    # now 63, bought gw5 at 60 -> 61
    conn.execute("UPDATE player_snapshot SET now_cost = 63 WHERE player_id = 8")
    conn.commit()
    t = [{"element_in": 8, "element_in_cost": 60, "element_out": 99, "element_out_cost": 55,
          "event": 5, "time": "2026-09-20T10:00:00Z"}]
    sq = load_squad(FakeEntryClient(transfers=t), conn, 1)
    assert next(p for p in sq.picks if p.player_id == 8).selling_price == 61


def test_selling_price_uses_latest_buy_and_ignores_future_transfers(conn):
    conn.execute("UPDATE player_snapshot SET now_cost = 69 WHERE player_id = 8")
    conn.commit()
    t = [
        {"element_in": 8, "element_in_cost": 60, "element_out": 90, "element_out_cost": 55,
         "event": 3, "time": "2026-09-01T10:00:00Z"},
        {"element_in": 91, "element_in_cost": 70, "element_out": 8, "element_out_cost": 63,
         "event": 5, "time": "2026-09-20T10:00:00Z"},
        {"element_in": 8, "element_in_cost": 65, "element_out": 92, "element_out_cost": 60,
         "event": 6, "time": "2026-09-27T10:00:00Z"},
        {"element_in": 10, "element_in_cost": 40, "element_out": 93, "element_out_cost": 40,
         "event": 10, "time": "2026-10-25T10:00:00Z"},
    ]
    sq = load_squad(FakeEntryClient(transfers=t), conn, 1)
    assert next(p for p in sq.picks if p.player_id == 8).selling_price == 67  # 65 + 4//2
    # GW10 transfer is after shown GW9: ignored, fallback buy 50 == now 50
    assert next(p for p in sq.picks if p.player_id == 10).selling_price == 50


def test_selling_price_kept_player_uses_first_gw_price(conn):
    conn.execute("INSERT INTO player_snapshot (season, gw, player_id, collected_at, status, chance_next, ep_next, now_cost, selected_by_percent) VALUES (?,?,?,?,?,?,?,?,?)",
                 (SEASON, 1, 3, "2026-08-10T12:00:00", "a", None, 1.0, 50, 5.0))
    conn.execute("UPDATE player_snapshot SET now_cost = 53 WHERE player_id = 3 AND gw = 9")
    conn.commit()
    client = FakeEntryClient()
    sq = load_squad(client, conn, 1)
    assert next(p for p in sq.picks if p.player_id == 3).selling_price == 51  # 50 + 3//2
    # player 4 has no gw1 snapshot -> element_summary fallback (value 50), now 50
    assert 4 in client.summary_calls
    assert next(p for p in sq.picks if p.player_id == 4).selling_price == 50


def test_gw1_buy_price_from_bootstrap_start_cost(conn):
    conn.execute("UPDATE player_snapshot SET now_cost = 56 WHERE player_id = 5 AND gw = 9")
    conn.commit()
    client = FakeEntryClient(elements=[
        {"id": 5, "now_cost": 56, "cost_change_start": 4},
        {"id": 6, "now_cost": 48, "cost_change_start": -2}])
    sq = load_squad(client, conn, 1)
    by_id = {p.player_id: p for p in sq.picks}
    assert by_id[5].selling_price == 54            # bought at 56 - 4 = 52, now 56
    assert by_id[6].selling_price == 50            # bought at 50, now 50
    assert 5 not in client.summary_calls and 6 not in client.summary_calls
    assert 7 in client.summary_calls               # not in bootstrap: element_summary fallback
    assert client.bootstrap_calls == 1


def test_later_first_gw_does_not_use_bootstrap(conn):
    client = FakeEntryClient(history={"current": [{"event": 3, "event_transfers": 0}], "chips": []},
                             elements=[{"id": 5, "now_cost": 56, "cost_change_start": 4}])
    load_squad(client, conn, 1)
    assert client.bootstrap_calls == 0 and 5 in client.summary_calls


def hist(rows, chips=()):
    return {"current": [{"event": e, "event_transfers": t} for e, t in rows],
            "chips": [{"name": n, "event": e} for n, e in chips]}


def test_free_transfers_cap_and_spend():
    idle = [(g, 0) for g in range(1, 8)]
    assert estimate_free_transfers(hist(idle)) == 5
    assert estimate_free_transfers(hist(idle + [(8, 2)])) == 4


def test_free_transfers_basics():
    assert estimate_free_transfers(hist([(1, 15)])) == 1  # GW1 does not count
    assert estimate_free_transfers(hist([(1, 0), (2, 3)])) == 1  # overspend floors at 0, +1
    assert estimate_free_transfers({"current": [], "chips": []}) == 1


def test_free_transfers_chip_weeks_keep_ft():
    rows = [(1, 0), (2, 0), (3, 8)]  # ft: 2 after gw2, gw3 wildcard -> stays 2, +1 = 3
    assert estimate_free_transfers(hist(rows, [("wildcard", 3)])) == 3


def test_validate_ok(conn):
    assert validate(make_squad(conn), conn) == []


def test_validate_three_per_club(conn):
    conn.execute("UPDATE player SET team_id = 1 WHERE player_id IN (3, 4, 5, 6)")
    conn.commit()
    problems = validate(make_squad(conn), conn)
    assert any("one club" in p for p in problems)


def test_validate_club_limit_names_the_club(conn):
    conn.execute("INSERT INTO team VALUES (?, 1, 'Arsenal', 'ARS')", (SEASON,))
    conn.execute("UPDATE player SET team_id = 1 WHERE player_id IN (3, 4, 5, 6)")
    conn.commit()
    problems = validate(make_squad(conn), conn)
    assert "Too many players from one club (ARS has 5, max 3)" in problems


def test_validate_budget_and_xi(conn):
    sq = make_squad(conn, bank=-1)
    assert any("budget" in p.lower() for p in validate(sq, conn))
    bad = Squad(1, 9, [Pick(p.player_id, p.slot, p.player_id in {1, 2, 3, 4, 8, 9, 10, 11, 12, 13, 14},
                            False, 50) for p in sq.picks], 0, 1)
    assert any("Starting XI" in p for p in validate(bad, conn))


def test_swap_rejects_cross_position(conn):
    with pytest.raises(SquadError, match="same position"):
        swap(make_squad(conn), 3, 22, conn)


def test_swap_rejects_over_budget(conn):
    with pytest.raises(SquadError, match="budget"):
        swap(make_squad(conn, bank=10), 8, 23, conn)  # costs 150, sells 50, bank 10


def test_swap_rejects_fourth_club_player(conn):
    sq = make_squad(conn)
    conn.execute("UPDATE player SET team_id = 1 WHERE player_id IN (3, 4, 5)")
    conn.commit()
    with pytest.raises(SquadError, match="one club"):
        swap(sq, 6, 21, conn)


def test_swap_keeps_captain_flag_and_updates_bank(conn):
    sq = make_squad(conn, bank=5)
    new = swap(sq, 9, 22, conn)
    assert new is not sq
    p = next(p for p in new.picks if p.player_id == 22)
    assert p.is_captain and p.is_starter and p.slot == 9 and p.selling_price == 50
    assert new.bank == 5 + 50 - 50
    assert next(p for p in sq.picks if p.slot == 9).player_id == 9  # original untouched
