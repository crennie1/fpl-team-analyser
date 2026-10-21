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


# ---- replacement list ----
def squad_payload(**top):
    """Squad of Raya (GK, ARS), Saka (MID, ARS) + a pool with a few MIDs."""
    pl = payload()
    pl["cards"].append(dict(pl["cards"][0], id=2, name="Saka", full_name="Bukayo Saka",
                            pos="MID", club="ARS", price=10.0))
    for c in pl["cards"]:
        c.update(selling_price=5.0, options=[], was=None, original_id=None)

    def row(i, name, club, price, xp3, full=None):
        return {"id": i, "name": name, "full_name": full or name, "initials": name[:2].upper(),
                "club": club, "price": price, "xp3": xp3,
                "fixtures": [{"opp": "BUR", "home": True, "fdr": 2}]}
    pl["pool"] = {"GK": [row(50, "Pickford", "EVE", 5.0, 9.0)],
                  "DEF": [],
                  "MID": [row(2, "Saka", "ARS", 10.0, 14.0),
                          row(10, "Palmer", "CHE", 10.5, 15.0),
                          row(11, "Mbeumo", "BRE", 7.5, 12.0),
                          row(12, "Odegaard", "ARS", 8.0, 11.0),
                          row(13, "Álvarez", "MCI", 9.0, 10.0)],
                  "FWD": [row(60, "Haaland", "MCI", 14.0, 20.0)]}
    pl["bank"] = 0.5
    pl.update(top)
    return pl


def list_html(pl, pick=1, after="openReplace()", **kw):
    import os
    os.environ["AFTER"] = after
    try:
        return render(pl, pick, **kw)["panel"]
    finally:
        del os.environ["AFTER"]


@needs_node
def test_replace_button_in_stats_panel():
    panel = render(squad_payload(), 1)["panel"]
    assert "Replace" in panel and "openReplace()" in panel


@needs_node
def test_replace_list_puts_options_first_with_thumbs():
    pl = squad_payload()
    pl["cards"][1]["options"] = [{"id": 11, "gain3": 3.2, "hit": 0, "starts_instead_of": None},
                                 {"id": 13, "gain3": 1.0, "hit": 0, "starts_instead_of": None}]
    panel = list_html(pl)
    assert "← back to stats" in panel and "Suggested for your team" in panel
    assert panel.index("Mbeumo") < panel.index("Álvarez") < panel.index("Palmer")
    assert "👍 +3.2 pts" in panel and "👍 +1.0 pts" in panel
    assert panel.count("👍") == 3   # header + 2 rows


@needs_node
def test_replace_list_excludes_squad_and_other_positions():
    panel = list_html(squad_payload())
    assert "Palmer" in panel and "Haaland" not in panel and "Pickford" not in panel
    assert 'data-in="2"' not in panel     # Saka himself is in the squad


@needs_node
def test_club_full_rows_greyed_with_reason():
    pl = squad_payload()
    for i in (3, 4):
        pl["cards"].append(dict(pl["cards"][1], id=i, name=f"X{i}", full_name=f"X{i}", club="CHE"))
    panel = list_html(pl)   # out = Saka (ARS); CHE has 2 -> Palmer fine
    assert "already 3 from this club" not in panel
    pl["cards"].append(dict(pl["cards"][1], id=5, name="X5", full_name="X5", club="CHE"))
    panel = list_html(pl)
    palmer = next(r for r in panel.split('<div class="rl') if "Palmer" in r)
    assert "already 3 from this club" in palmer and "data-in" not in palmer
    assert 'data-in="11"' in panel


@needs_node
def test_club_count_ignores_the_player_leaving():
    """Replacing an ARS player with ARS squad count 3 still allows another ARS player."""
    pl = squad_payload()
    pl["cards"].append(dict(pl["cards"][1], id=3, name="X3", full_name="X3", club="ARS"))
    panel = list_html(pl)   # Raya, Saka, X3 = 3 ARS; Saka leaves -> 2
    assert 'data-in="12"' in panel and "already 3 from this club" not in panel


@needs_node
def test_amber_price_when_unaffordable():
    panel = list_html(squad_payload())   # cap = 0.5 + 5.0 = 5.5
    assert 'class="pr amb">£7.5m' in panel
    pl = squad_payload(bank=3.0)         # cap 8.0
    panel = list_html(pl)
    assert 'class="pr">£7.5m' in panel and 'class="pr amb">£9.0m' in panel


@needs_node
def test_no_options_over_budget_message():
    msg = "No player in this position gets you back within budget"
    assert msg in list_html(squad_payload(bank=-1.0))
    assert msg not in list_html(squad_payload(bank=1.0))
    pl = squad_payload(bank=-1.0)
    pl["cards"][1]["options"] = [{"id": 11, "gain3": 1.0, "hit": 0, "starts_instead_of": None}]
    assert msg not in list_html(pl)


@needs_node
def test_hit_shown_on_option():
    pl = squad_payload()
    pl["cards"][1]["options"] = [{"id": 11, "gain3": 3.2, "hit": 4, "starts_instead_of": None}]
    assert "+3.2 pts, −4 hit" in list_html(pl)
    pl["cards"][1]["options"][0]["hit"] = 0
    assert "hit" not in list_html(pl).split("Mbeumo")[1].split("Palmer")[0]


@needs_node
def test_names_escaped_in_list():
    pl = squad_payload()
    pl["pool"]["MID"][1]["name"] = "<b>Evil</b>"
    pl["pool"]["MID"][1]["full_name"] = "<b>Evil</b>"
    pl["error"] = "bad <i>x</i>"
    panel = list_html(pl)
    assert "&lt;b&gt;Evil&lt;/b&gt;" in panel and "<b>Evil" not in panel
    assert "bad &lt;i&gt;x&lt;/i&gt;" in panel


@needs_node
def test_search_is_case_and_accent_insensitive():
    panel = list_html(squad_payload(), after="openReplace();setQ('ALVAREZ')")
    assert "Álvarez" in panel and "Palmer" not in panel


@needs_node
def test_sort_by_price_and_club():
    p1 = list_html(squad_payload(), after="openReplace();setSort('price')")
    assert p1.index("Palmer") < p1.index("Álvarez") < p1.index("Mbeumo")
    p2 = list_html(squad_payload(), after="openReplace();setSort('club')")
    assert p2.index("Mbeumo") < p2.index("Palmer") < p2.index("Álvarez")


@needs_node
def test_row_click_sends_swap():
    out = render(squad_payload(), 1, frame=True)
    import os
    os.environ["AFTER"] = "openReplace();swapIn(11)"
    try:
        out = render(squad_payload(), 1, frame=True)
    finally:
        del os.environ["AFTER"]
    value = next(m for m in out["posted"] if m["type"] == "streamlit:setComponentValue")
    assert value["value"] == {"type": "swap", "out_id": 2, "in_id": 11, "n": 1}


@needs_node
def test_error_shown_in_stats_panel():
    assert 'class="warn">bad' in render(squad_payload(error="bad move"), 1)["panel"]


@needs_node
def test_list_mode_survives_rerun_and_resets_after_swap():
    import os
    pl = squad_payload()
    os.environ["AFTER"] = "openReplace();setQ('pal');render(" + json.dumps(pl) + ")"
    try:
        panel = render(pl, 1)["panel"]
        assert "← back to stats" in panel and 'value="pal"' in panel
        pl2 = squad_payload(focus_id=1)
        os.environ["AFTER"] = ("openReplace();setQ('pal');swapIn(11);render(" + json.dumps(pl2) + ")")
        panel = render(pl2, 1)["panel"]
    finally:
        del os.environ["AFTER"]
    assert "← back to stats" not in panel and "David Raya" in panel


@needs_node
def test_phone_panel_stays_under_selected_row_after_rerun(tmp_path):
    cards = []
    for i, pos in enumerate(["GK", "DEF", "MID", "FWD"]):
        cards.append(payload(pos=pos, id=i, name=f"P{i}")["cards"][0])
    pl = payload()
    pl["cards"] = cards
    js, data = page_script(tmp_path, pl)
    again = tmp_path / "again.json"
    harness = Path(__file__).parent / "js" / "pick_harness.js"

    def run(next_pl):
        again.write_text(json.dumps(next_pl))
        out = subprocess.run(["node", str(harness), str(js), str(data), "2", str(again)],
                             capture_output=True, text=True, check=False)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)
    res = run(pl)                                     # same payload: still under the MID row
    assert res["open"] and res["afterNode"] == "panel" and res["afterRow"] == ["MID"]
    res = run(dict(pl, focus_id=1))                   # a swap brought focus to the DEF
    assert res["open"] and res["afterRow"] == ["DEF"]


# ---- plan bar, IN tags, before-vs-after ----
def plan_payload(**top):
    pl = squad_payload()
    pl["cards"][1].update(was="Bruno", original_id=7)
    pl["ft"] = 1
    pl["base_grades"] = {"attack": "B"}
    pl["plan"] = {
        "changes": [{"out_id": 7, "out_name": "Bruno <b>", "out_price": 8.0, "in_id": 2,
                     "in_name": "Saka", "in_price": 10.0, "diff": 2.0}],
        "n_changes": 1, "ft_used": 1, "hit": 0, "bank": 0.5,
        "compare": {"pts3": [10.0, 14.0], "pts3_after_hits": [10.0, 14.0],
                    "grades": [["attack", "B", "A"]], "bank": [2.5, 0.5]}}
    pl.update(top)
    return pl


@needs_node
def test_no_plan_no_bar_tags_or_section():
    pl = squad_payload()
    pl["ft"] = 2
    pl["plan"] = None
    out = render(pl, 1)
    assert "Free transfers" in out["bar"] and "setFt(3)" in out["bar"]
    for bad in ("Your plan", "Undo last", "Reset to my team"):
        assert bad not in out["bar"]
    assert out["plan"] == "" and "IN ·" not in out["pitch"] and "▲" not in out["grades"]


@needs_node
def test_in_tag_and_undo_send_original_id():
    out = render(plan_payload(), 1, frame=True, send={"type": "undo", "original_id": 7})
    assert "IN · was Bruno" in out["pitch"] and "undoCard(7)" in out["pitch"]
    value = next(m for m in out["posted"] if m["type"] == "streamlit:setComponentValue")
    assert value["value"] == {"type": "undo", "original_id": 7, "n": 1}
    import os
    os.environ["AFTER"] = "undoCard(7)"
    try:
        out = render(plan_payload(), 1, frame=True)
    finally:
        del os.environ["AFTER"]
    assert [m["value"] for m in out["posted"] if m["type"] == "streamlit:setComponentValue"] == [
        {"type": "undo", "original_id": 7, "n": 1}]


@needs_node
def test_bar_pills_hit_and_over_budget_only_when_nonzero():
    bar = render(plan_payload(), 1)["bar"]
    assert "1 change" in bar and "1 free transfer used" in bar
    assert "pt hit" not in bar and "over budget" not in bar
    assert "Undo last" in bar and "Reset to my team" in bar and "undo_last" in bar and "'reset'" in bar
    pl = plan_payload()
    pl["plan"].update(n_changes=3, ft_used=2, hit=4, bank=-0.8)
    bar = render(pl, 1)["bar"]
    assert "3 changes" in bar and "2 free transfers used" in bar
    assert "−4 pt hit" in bar and "£0.8m over budget" in bar


@needs_node
def test_plan_section_copy_and_rows():
    pl = plan_payload()
    pl["plan"]["changes"].append(dict(pl["plan"]["changes"][0], out_name="Cole", in_name="Foden",
                                      out_price=7.0, in_price=7.0, diff=0.0))
    sec = render(pl, 1)["plan"]
    assert "Your plan vs your real team" in sec
    assert "Make these in the FPL app. This site never changes your real team." in sec
    assert sec.count('class="outin"') == 2
    assert "Bruno &lt;b&gt;" in sec and "<b>" not in sec.split("Bruno")[1].split("→")[0]
    assert "−£2.0m" in sec and "£0.0m" in sec    # dearer incoming player = money spent
    assert "Pts next 3 wks" in sec and "+4.0" in sec and "▲" in sec and "£0.5m" in sec


@needs_node
def test_plan_section_freed_money_has_plus_sign():
    pl = plan_payload()
    pl["plan"]["changes"][0].update(out_price=10.0, in_price=7.2, diff=-2.8)
    sec = render(pl, 1)["plan"]
    assert '<span class="d up">+£2.8m</span>' in sec


@needs_node
def test_grade_arrow_when_letter_changes():
    assert "▲" in render(plan_payload(), 1)["grades"]
    assert "▼" in render(plan_payload(base_grades={"attack": "A"}, grades={"attack": "C"}), 1)["grades"]
    g = render(plan_payload(base_grades={"attack": "A"}, grades={"attack": "A"}), 1)["grades"]
    assert "▲" not in g and "▼" not in g


@needs_node
def test_list_header_names_position_and_search_resets_on_other_card():
    pl = squad_payload()
    pl["cards"][1]["options"] = [{"id": 11, "gain3": 3.2, "hit": 0, "starts_instead_of": None}]
    assert "All midfielders" in list_html(pl) and "Everyone else" not in list_html(pl)
    import os
    os.environ["AFTER"] = "openReplace();setQ('pal');pick(0)"
    try:
        out = render(squad_payload(), 1)
        os.environ["AFTER"] = "openReplace();setQ('pal');pick(0);pick(1);openReplace()"
        out2 = render(squad_payload(), 1)
    finally:
        del os.environ["AFTER"]
    assert 'value=""' in out2["panel"]


@needs_node
def test_set_ft_sends_clamped_value():
    import os
    os.environ["AFTER"] = "setFt(9);setFt(-2);setFt(3)"
    try:
        out = render(plan_payload(), 1, frame=True)
    finally:
        del os.environ["AFTER"]
    assert [m["value"]["ft"] for m in out["posted"] if m["type"] == "streamlit:setComponentValue"] == [5, 0, 3]
