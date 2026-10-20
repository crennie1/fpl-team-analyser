import json
import re
from pathlib import Path

from fpl.ui.kits import DEFAULT_KIT, KITS
from app import team_view_html


def payload(**card):
    c = {"id": 1, "initials": "AB", "name": "Raya", "full_name": "David Raya", "pos": "GK",
         "club": "ARS", "price": 5.5, "owned": "31.0", "xp": 4.0, "xp3": 12.0, "colour": "green",
         "flag": None, "starter": True, "captain": False, "bar_label": "Clean sheet",
         "bar_pct": 40, "fixtures": [{"opp": "BUR", "home": True, "fdr": 2}],
         "last6": {"form": 5.0, "xg": None, "xa": None, "defcon_pct": None},
         "weakness": None, "set_pieces": None, "sell": None}
    c.update(card)
    return {"cards": [c], "grades": {"attack": "A"}, "projected": 61.5, "average": 53.5,
            "kits": KITS, "weakness": []}


def data_of(html):
    m = re.search(r"const DATA = (.*?);\n", html, re.S)
    return json.loads(m.group(1))


def test_component_escapes_names():
    html = team_view_html(payload(name="O'Brien</script><b>&", full_name="x</script>"))
    assert html.count("</script>") == 1                  # only the page's own closing tag
    assert data_of(html)["cards"][0]["name"] == "O'Brien</script><b>&"


def test_component_gk_label():
    html = team_view_html(payload())
    assert "Clean sheet chance" in html


def test_kits_cover_current_clubs():
    import sqlite3
    conn = sqlite3.connect(Path(__file__).parent.parent / "data" / "fpl.db")
    shorts = [r[0] for r in conn.execute(
        "SELECT short_name FROM team WHERE season = (SELECT value FROM meta WHERE key='current_season')")]
    assert len(shorts) == 20 and all(s in KITS for s in shorts)
    for k in KITS.values():
        assert k["pattern"] in ("plain", "stripes", "hoops")
        assert k["pattern"] == "plain" or len(k["pattern_colors"]) == 2
    assert DEFAULT_KIT["pattern"] == "plain"


def test_sell_panel_has_note_and_hit_label():
    sell = {"to_name": "Cherki", "to_full_name": "Rayan Cherki", "to_club": "MCI", "gain3": 18.0,
            "hit": 4, "starts_instead_of": "Rogers"}
    html = team_view_html(payload(sell=sell))
    assert "Best single move" in html and "hit" in html and "starts instead of" in html
    assert data_of(html)["cards"][0]["sell"]["hit"] == 4
