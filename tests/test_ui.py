import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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
            "kits": KITS}


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


def test_sell_data_is_embedded_not_static_text():
    sell = {"to_name": "Cherki", "to_full_name": "Rayan Cherki", "to_club": "MCI", "gain3": 18.0,
            "hit": 4, "starts_instead_of": "Rogers"}
    d = data_of(team_view_html(payload(sell=sell)))["cards"][0]["sell"]
    assert d == sell
    # without a sell the data carries none, so the panel's sell block cannot render
    html = team_view_html(payload(sell=None))
    assert data_of(html)["cards"][0]["sell"] is None
    assert "Rayan Cherki" not in html


def test_template_sell_block_is_data_driven():
    src = (Path(__file__).parent.parent / "fpl" / "ui" / "team_view.html").read_text()
    assert "s.hit?" in src and "s.starts_instead_of?" in src and "p.sell" in src


def test_narrow_screens_open_panel_inline_after_row():
    src = (Path(__file__).parent.parent / "fpl" / "ui" / "team_view.html").read_text()
    media = src.split("@media(max-width:760px)")[1].split("</style>")[0]
    assert "position:fixed" not in media and "position:static" in media
    assert "row.after(panel)" in src and "innerWidth<=760" in src
    assert "position:fixed" not in src


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_phone_tap_opens_panel_after_the_tapped_cards_row(tmp_path):
    """Payload order (GK first) differs from pitch order (FWD, MID, DEF, GK): the MID's panel
    must land after the MID row."""
    cards = []
    for i, pos in enumerate(["GK", "DEF", "MID", "FWD"]):
        base = payload(pos=pos, id=i, name=f"P{i}", bar_label="Clean sheet" if pos == "GK" else "DefCon")
        cards.append(base["cards"][0])
    pl = payload()
    pl["cards"] = cards
    html = team_view_html(pl)
    js = tmp_path / "page.js"
    js.write_text(re.search(r"<script>(.*)</script>", html, re.S).group(1))
    harness = Path(__file__).parent / "js" / "pick_harness.js"
    for idx, pos in ((2, "MID"), (1, "DEF"), (3, "FWD"), (0, "GK")):
        out = subprocess.run(["node", str(harness), str(js), str(idx)], capture_output=True,
                             text=True, check=False)
        assert out.returncode == 0, out.stderr
        out = out.stdout
        res = json.loads(out)
        assert res["open"] and res["afterNode"] == "panel"
        assert res["afterRow"] == [pos]
