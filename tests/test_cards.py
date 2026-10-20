"""Tests for fpl/cards.py on the tiny v2db league (team 1 v team 2 every gameweek)."""
import pytest

from fpl.analyse import Analysis, PlayerView
from fpl.cards import ordinal, player_cards, weakness_table
from fpl.suggest import Suggestion
from tests.conftest import _insert
from tests.test_forecast_v2 import CUR, add_stat_row, refresh
from tests.test_forecast_v2 import v2db  # noqa: F401  (fixture)


def add(conn, pid, pos, team, first=None, second=None, web="Web", defcon=None, cs=None,
        xp=4.0, xp3=10.0, cost=65, owned=12.5):
    _insert(conn, "player", [{"season": CUR, "player_id": pid, "web_name": web, "team_id": team,
                              "position": pos, "first_name": first, "second_name": second}])
    _insert(conn, "player_snapshot", [{
        "season": CUR, "gw": 7, "player_id": pid, "collected_at": "x", "status": "a",
        "chance_next": None, "ep_next": 4.0, "now_cost": cost, "selected_by_percent": owned,
        "news": None}])
    conn.execute("INSERT OR REPLACE INTO xp_next_cache VALUES (?, ?, ?, 1.0, 'v2', ?, ?)",
                 (pid, xp, xp3, defcon, cs))


def setup_league(conn):
    _insert(conn, "team", [{"season": CUR, "team_id": t, "name": f"Team {t}", "short_name": f"T{t}"}
                           for t in (1, 2, 3)])


def view(pid, name, pos, club="T1"):
    return PlayerView(pid, name, pos, club, 4.0, "green", None, True, False)


def analysis(*views):
    return Analysis(list(views), {}, 0.0, 0.0, 7, None)


def test_cards_keys_and_initials(v2db):
    setup_league(v2db)
    add(v2db, 1, "FWD", 1, "Erling", "Haaland", "Haaland")
    add(v2db, 2, "MID", 1, None, None, "Salah")
    add(v2db, 3, "MID", 1, "Kevin", "De Bruyne", "De Bruyne")
    refresh(v2db)
    cards = player_cards(v2db, analysis(view(1, "Haaland", "FWD"), view(2, "Salah", "MID"),
                                        view(3, "De Bruyne", "MID")), [])
    assert [c["initials"] for c in cards] == ["EH", "SA", "KD"]
    assert set(cards[0]) == {"id", "initials", "name", "full_name", "pos", "club", "price", "owned",
                             "xp", "xp3", "colour", "flag", "starter", "captain", "bar_label",
                             "bar_pct", "fixtures", "last6", "weakness", "set_pieces", "sell"}
    c = cards[0]
    assert (c["full_name"], c["price"], c["owned"], c["club"]) == ("Erling Haaland", 6.5, 12.5, "T1")
    assert cards[1]["full_name"] == "Salah"
    assert len(c["fixtures"]) == 3 and c["fixtures"][0] == {"opp": "T2", "home": True, "fdr": 3}


def test_cards_goalkeeper_cs(v2db):
    setup_league(v2db)
    add(v2db, 1, "GK", 1, defcon=0.0, cs=0.37)
    refresh(v2db)
    c = player_cards(v2db, analysis(view(1, "Gk", "GK")), [])[0]
    assert (c["bar_label"], c["bar_pct"], c["last6"]["defcon_pct"]) == ("Clean sheet", 37, None)


def test_cards_outfield_defcon(v2db):
    setup_league(v2db)
    add(v2db, 1, "MID", 1, defcon=0.64, cs=0.3)
    refresh(v2db)
    c = player_cards(v2db, analysis(view(1, "M", "MID")), [])[0]
    assert (c["bar_label"], c["bar_pct"]) == ("DefCon", 64)


def test_cards_sell_mapping(v2db):
    setup_league(v2db)
    add(v2db, 1, "MID", 1)
    add(v2db, 2, "MID", 2, "Bukayo", "Saka", "Saka")
    refresh(v2db)
    s = Suggestion(1, 2, "M", "Saka", 3.5, 4, -0.5, ("midfield", "B", "A"), starts_instead="Other")
    cards = player_cards(v2db, analysis(view(1, "M", "MID")), [s])
    assert cards[0]["sell"] == {"to_name": "Saka", "to_full_name": "Bukayo Saka", "to_club": "T2",
                                "gain3": 3.5, "hit": 4, "starts_instead_of": "Other"}
    assert player_cards(v2db, analysis(view(1, "M", "MID")), [])[0]["sell"] is None


def test_cards_new_player(v2db):
    setup_league(v2db)
    add(v2db, 1, "DEF", 1, defcon=None)
    refresh(v2db)
    c = player_cards(v2db, analysis(view(1, "New", "DEF")), [])[0]
    assert c["last6"] == {"form": None, "xg": None, "xa": None, "defcon_pct": None}
    assert c["bar_pct"] is None and c["set_pieces"] is None


def test_cards_last6_and_set_pieces(v2db):
    setup_league(v2db)
    add(v2db, 1, "MID", 1)
    add_stat_row(v2db, 2, 1, 1, pts=8, xg=0.5, xa=0.25, hits=1)
    add_stat_row(v2db, 3, 1, 1, pts=2, xg=0.25, xa=0.0, hits=0)
    _insert(v2db, "set_piece", [{"season": CUR, "player_id": 1, "penalties_order": 1,
                                 "corners_order": 1, "direct_fk_order": 2, "collected_at": "x"}])
    refresh(v2db)
    c = player_cards(v2db, analysis(view(1, "M", "MID")), [])[0]
    assert c["last6"]["form"] == pytest.approx(5.0)
    assert c["last6"]["xg"] == pytest.approx(0.75) and c["last6"]["xa"] == pytest.approx(0.25)
    assert c["last6"]["defcon_pct"] is not None
    assert c["set_pieces"] == "1st choice penalties, corners; 2nd choice direct free kicks"


def _weak_league(conn):
    setup_league(conn)
    add(conn, 1, "MID", 1)
    add(conn, 2, "MID", 2)
    add_stat_row(conn, 3, 1, 1, pts=6)     # team 1's MID scores 6 against team 2
    add_stat_row(conn, 4, 1, 1, pts=6)
    add_stat_row(conn, 3, 2, 2, pts=2)     # team 2's MID scores 2 against team 1
    add_stat_row(conn, 4, 2, 2, pts=2)
    refresh(conn)


def test_weakness_rank(v2db):
    _weak_league(v2db)
    rows = {r["short"]: r for r in weakness_table(v2db)}
    assert rows["T2"]["mid"] == pytest.approx(6.0) and rows["T2"]["rank"]["mid"] == 1
    assert rows["T1"]["mid"] == pytest.approx(2.0) and rows["T1"]["rank"]["mid"] == 2
    assert rows["T3"]["mid"] is None and rows["T3"]["rank"]["mid"] is None
    assert set(rows["T1"]) == {"team", "short", "gk", "def", "mid", "fwd", "rank"}


def test_weakness_sentence(v2db):
    _weak_league(v2db)
    c = player_cards(v2db, analysis(view(1, "M", "MID")), [])[0]
    assert c["weakness"] == "T2 concede the 1st-most points to midfielders over the last 6 GWs"
    c2 = player_cards(v2db, analysis(view(2, "M", "MID", "T2")), [])[0]
    assert c2["weakness"].startswith("T1 concede the 2nd-most")


def test_ordinals():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 20, 21)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "20th", "21st"]


def test_cards_initials_v6(v2db):
    setup_league(v2db)
    add(v2db, 1, "GK", 1, "David", "Raya Martín", "Raya")
    add(v2db, 2, "MID", 1, "Bruno", "Borges Fernandes", "B.Fernandes")
    add(v2db, 3, "DEF", 1, "Gabriel", "dos Santos Magalhães", "Gabriel")
    refresh(v2db)
    cards = player_cards(v2db, analysis(view(1, "Raya", "GK"), view(2, "B.Fernandes", "MID"),
                                        view(3, "Gabriel", "DEF")), [])
    assert [c["initials"] for c in cards] == ["DR", "BF", "GG"]


def test_cards_skip_player_missing_from_db(v2db):
    setup_league(v2db)
    add(v2db, 1, "MID", 1)
    refresh(v2db)
    cards = player_cards(v2db, analysis(view(99, "Ghost", "MID"), view(1, "M", "MID")), [])
    assert [c["id"] for c in cards] == [1]
