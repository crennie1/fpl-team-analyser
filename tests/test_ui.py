import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from fpl.ui.kits import DEFAULT_KIT, KITS

PAGE = Path(__file__).parent.parent / "fpl" / "ui" / "team_sheet" / "index.html"


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


def page_script(tmp_dir, pl):
    """The page's script and its payload as files for the node harnesses."""
    js, data = Path(tmp_dir) / "page.js", Path(tmp_dir) / "payload.json"
    js.write_text(re.search(r"<script>(.*)</script>", PAGE.read_text(), re.S).group(1))
    data.write_text(json.dumps(pl))
    return js, data


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


def test_template_sell_block_is_data_driven():
    src = PAGE.read_text()
    assert "s.hit?" in src and "s.starts_instead_of?" in src and "p.sell" in src


def test_page_has_no_embedded_data():
    """The payload arrives by message (render), never baked into the page."""
    src = PAGE.read_text()
    assert "/*DATA*/" not in src and "streamlit:render" in src and "componentReady" in src


def test_narrow_screens_open_panel_inline_after_row():
    src = PAGE.read_text()
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
    js, data = page_script(tmp_path, pl)
    harness = Path(__file__).parent / "js" / "pick_harness.js"
    for idx, pos in ((2, "MID"), (1, "DEF"), (3, "FWD"), (0, "GK")):
        out = subprocess.run(["node", str(harness), str(js), str(data), str(idx)],
                             capture_output=True,
                             text=True, check=False)
        assert out.returncode == 0, out.stderr
        out = out.stdout
        res = json.loads(out)
        assert res["open"] and res["afterNode"] == "panel"
        assert res["afterRow"] == [pos]


def render(pl, pick=None, frame=False, send=None):
    """Run the page script's render(pl) in node against a stub DOM;
    return {"pitch": html, "panel": html, "grades": html, "posted": [messages]}.

    frame=True runs it as Streamlit does: inside a parent frame, drawn by a streamlit:render
    message; `send` is then an action passed to the page's send() at the end."""
    import os
    import tempfile
    env = {**os.environ, "FRAME": "1" if frame else "", "SEND": json.dumps(send) if send else ""}
    with tempfile.TemporaryDirectory() as d:
        js, data = page_script(d, pl)
        harness = Path(__file__).parent / "js" / "render_harness.js"
        args = ["node", str(harness), str(js), str(data)] + ([] if pick is None else [str(pick)])
        out = subprocess.run(args, capture_output=True, text=True, check=False, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@needs_node
def test_card_xp_colour_follows_payload_colour():
    """v1's rule (chance <= 50% -> red) lives in `colour`; the card must not recolour by xP."""
    for colour, xp, css in (("red", 6.0, "#ff5c7a"), ("green", 1.0, "#38d39f"),
                            ("amber", 6.0, "#fff")):
        pitch = render(payload(colour=colour, xp=xp))["pitch"]
        assert f'<div class="xp" style="color:{css}">' in pitch, colour


@needs_node
def test_panel_defcon_hits_shows_raw_count():
    pl = payload(pos="DEF", bar_label="DefCon", bar_pct=55,
                 last6={"form": 5.0, "xg": 0.2, "xa": 0.1, "defcon_pct": 67,
                        "defcon_hits": 4, "defcon_apps": 6})
    panel = render(pl, 0)["panel"]
    assert "DefCon hits" in panel and ">4 of 6<" in panel and ">67%<" not in panel


@needs_node
def test_sell_block_uses_payload_initials():
    sell = {"to_name": "B.Fernandes", "to_full_name": "Bruno Borges Fernandes", "to_club": "ZZZ",
            "initials": "BF", "gain3": 3.0, "hit": 0, "starts_instead_of": None}
    panel = render(payload(sell=sell), 0)["panel"]
    assert ">BF</text>" in panel and ">BB</text>" not in panel


@needs_node
def test_render_escapes_names():
    out = render(payload(name="O'Brien</script><b>&", full_name="x</script>"), 0)
    assert "O&#39;Brien&lt;/script&gt;&lt;b&gt;&amp;" in out["pitch"]
    assert "</script>" not in out["pitch"] + out["panel"]


@needs_node
def test_panel_sell_block_follows_payload():
    sell = {"to_name": "Cherki", "to_full_name": "Rayan Cherki", "to_club": "MCI", "gain3": 18.0,
            "initials": "RC", "hit": 4, "starts_instead_of": "Rogers"}
    panel = render(payload(sell=sell), 0)["panel"]
    assert "Rayan Cherki" in panel and "−4 hit" in panel and "starts instead of Rogers" in panel
    assert "Rayan Cherki" not in render(payload(sell=None), 0)["panel"]


@needs_node
def test_render_redraws_grades_from_payload():
    out = render(payload(), 0)
    assert "61.5 pts" in out["grades"] and ">A<" in out["grades"]


@needs_node
def test_render_selects_focus_card():
    pl = payload()
    other = dict(pl["cards"][0], id=2, name="Saka", full_name="Bukayo Saka", pos="MID")
    pl["cards"].append(other)
    pl["focus_id"] = 2
    assert "Bukayo Saka" in render(pl)["panel"]


@needs_node
def test_bridge_ready_height_and_send():
    """In a frame the page says it is ready, reports its height after each draw, and send()
    numbers every action, continuing from the payload's last seen number."""
    pl = payload()
    pl["n"] = 7
    out = render(pl, 0, frame=True, send={"type": "reset"})
    types = [m["type"] for m in out["posted"]]
    assert types[0] == "streamlit:componentReady" and out["posted"][0]["apiVersion"] == 1
    assert "streamlit:setFrameHeight" in types
    value = next(m for m in out["posted"] if m["type"] == "streamlit:setComponentValue")
    assert value["value"] == {"type": "reset", "n": 8} and value["dataType"] == "json"
