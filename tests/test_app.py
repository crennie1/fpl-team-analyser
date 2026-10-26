from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from fpl import api, db
from fpl.api import FplApiError

APP = str(Path(__file__).parent.parent / "app.py")
USER = 9000          # user squad players are 9001..9015 (teams 1-7, so no club has more than 3)
POOL = 9100          # swap targets 9101..9115, all on team 8, xp 15
TEAM_ID = "1234567"


class FakeApp:
    """Stands in for FplClient: serves the 'user' squad from the test database."""

    error = None

    def __init__(self):
        pass

    def entry(self, tid):
        if self.error:
            raise self.error
        return {"current_event": 5}

    def entry_picks(self, tid, gw):
        return {"active_chip": None, "entry_history": {"bank": 0},
                "picks": [{"element": USER + s, "position": s, "is_captain": s == 9}
                          for s in range(1, 16)]}

    def entry_history(self, tid):
        return {"current": [{"event": 1, "event_transfers": 0}], "chips": []}

    def entry_transfers(self, tid):
        return []

    def element_summary(self, pid):
        return {"history": []}

    def bootstrap(self):
        return {"elements": []}


@pytest.fixture(autouse=True)
def clean_caches():
    st.cache_data.clear()
    st.cache_resource.clear()
    FakeApp.error = None
    yield


@pytest.fixture
def env(db_with_squads, add_squad, monkeypatch):
    conn = db_with_squads
    add_squad(conn, "user", USER, xp=4.0)
    add_squad(conn, "pool", POOL, xp=15.0)
    conn.execute("DELETE FROM squad_pick WHERE squad_id IN ('user', 'pool')")
    conn.executemany("INSERT OR IGNORE INTO team VALUES ('2026-27', ?, ?, ?)",
                     [(t, f"Team {t}", f"T{t}") for t in range(1, 9)])
    for slot in range(1, 16):
        conn.execute("UPDATE player SET team_id = ? WHERE player_id = ?",
                     ((slot % 7) + 1, USER + slot))
        conn.execute("UPDATE player SET team_id = 8 WHERE player_id = ?", (POOL + slot,))
    # swap targets need fixtures: xP is the player's average times his fixtures
    conn.executemany("INSERT INTO fixture (season, fixture_id, gw, team_h, team_a, team_h_difficulty, "
                     "team_a_difficulty, finished) VALUES ('2026-27', ?, ?, 8, 4, 3, 3, 0)",
                     [(200 + gw, gw) for gw in range(6, 11)])
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_collected', ?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    conn.commit()
    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    monkeypatch.setenv("FPL_DB", path)
    monkeypatch.setattr(api, "FplClient", FakeApp)
    return conn


def run(team=TEAM_ID):
    at = AppTest.from_file(APP, default_timeout=30)
    if team is not None:
        at.query_params["team"] = team
    return at.run()


def text(at):
    return " ".join(m.value for m in at.markdown)


def payload(at):
    """The data the team sheet was last given (the app keeps a copy in session state)."""
    return at.session_state["team_payload"]


# Streamlit is pinned to 1.66.0: act() uses AppTest's private _tree and _run.
def act(at, action):
    """Post `action` from the team sheet, as the page's send() does, and rerun."""
    import json
    from streamlit.proto.WidgetStates_pb2 import WidgetStates
    sheet = at.get("component_instance")
    assert len(sheet) == 1
    states = WidgetStates()
    states.widgets.extend(at._tree.get_widget_states().widgets)
    act.n = getattr(act, "n", 0) + 1
    w = states.widgets.add()
    w.id = sheet[0].proto.id
    w.json_value = json.dumps({**action, "n": act.n})
    return at._run(widget_state=states)


def plan_state(moves, ft=1, team=TEAM_ID):
    return {"team": team, "moves": moves, "ft": ft, "last_n": 0, "error": None, "focus_id": None}


def sells(at):
    return {c["name"]: c["sell"] for c in payload(at)["cards"] if c["sell"]}


def test_app_renders_component(env):
    at = run()
    assert not at.exception
    p = payload(at)
    assert list(p["grades"]) == ["Attack", "Midfield", "Defence", "Fixtures (next 5)",
                                 "Injury / rotation risk", "Bench"]
    assert len(p["grades"]) == 6 and p["projected"] > 0 and p["average"] > 0
    assert sum(c["starter"] for c in p["cards"]) == 11 and len(p["cards"]) == 15
    assert next(c for c in p["cards"] if c["name"] == "P9009")["captain"]
    assert "Analysing your GW5 squad" in text(at)
    assert not any("Suggested moves" in m.value for m in at.markdown)   # old list is gone
    assert at.tabs[0].label == "Your team"
    assert p["plan"] is None and p["ft"] == 1 and p["bank"] == 0.0 and p["error"] is None
    assert p["base_grades"] == p["grades"]
    assert {c["id"] for c in p["pool"]["FWD"]} >= {POOL + 10, POOL + 15}
    sheet = at.get("component_instance")
    assert len(sheet) == 1
    import json
    assert json.loads(sheet[0].proto.json_args)["payload"] == p     # what the page draws


def test_app_has_no_edit_squad_box(env):
    at = run()
    assert not at.get("expandable")
    assert not at.selectbox and not at.number_input and len(at.button) == 1   # just Analyse


def test_app_weakness_tab(env):
    at = run()
    assert at.tabs[1].label == "Opponent weaknesses"
    df = at.dataframe[0].value
    assert list(df.columns) == ["GK", "DEF", "MID", "FWD", "GK xG", "DEF xG", "MID xG", "FWD xG"]
    assert len(df) == 8                                      # the sample's teams
    assert "weakness" not in payload(at)                     # the component never read it


def test_app_weakness_table_computed_once_per_database(env, monkeypatch):
    """The weakness table is cached per database file: one computation across reruns."""
    from fpl import cards
    calls = []
    real = cards.weakness_table
    monkeypatch.setattr(cards, "weakness_table", lambda conn: calls.append(1) or real(conn))
    at = run()
    at.run()
    assert not at.exception
    assert len(calls) == 1


def test_app_replacement_pool_computed_once_per_database(env, monkeypatch):
    from fpl import cards
    calls = []
    real = cards.replacement_pool
    monkeypatch.setattr(cards, "replacement_pool", lambda conn: calls.append(1) or real(conn))
    at = run()
    at.run()
    assert not at.exception
    assert len(calls) == 1


def test_app_api_down_message(env):
    FakeApp.error = FplApiError("down", status=503)
    at = run()
    assert "FPL data is unavailable right now" in at.error[0].value


def test_app_bad_id_message(env):
    at = run("abc")
    assert "Team ID must be a number" in at.error[0].value


def test_app_form_submit_sets_team_link(env):
    at = run(None)
    assert not at.error and not at.exception
    at.text_input(key="team_id").input(TEAM_ID)
    at.button[0].click().run()
    assert at.query_params["team"] == TEAM_ID
    assert payload(at)["projected"] > 0


def test_app_stale_warning(env):
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    env.execute("UPDATE meta SET value = ? WHERE key = 'last_collected'", (old,))
    env.commit()
    at = run()
    assert "Player data may be out of date" in at.warning[0].value
    assert old in at.warning[0].value


def test_app_fresh_data_has_no_warning(env):
    assert not run().warning


def test_app_footer_source_and_repo_link(env, monkeypatch):
    monkeypatch.setenv("REPO_URL", "https://github.com/example/fpl")
    at = run()
    foot = " ".join(c.value for c in at.caption)
    assert "official FPL API" in foot and "recent average" in foot
    assert "(next week)" in foot and "(3 weeks)" in foot
    assert "https://github.com/example/fpl/blob/main/reports/backtest.md" in foot


def test_app_plan_from_session_moves(env):
    from fpl.plan import Move
    at = run()
    before = payload(at)["projected"]
    old_xp = next(c["xp"] for c in payload(at)["cards"] if c["id"] == USER + 10)
    at.session_state["plan"] = plan_state([Move(USER + 10, POOL + 10)])   # a starting FWD swapped for a pool player
    at.run()
    assert not at.exception
    p = payload(at)
    assert p["plan"]["n_changes"] == 1 and "P9110" in [c["name"] for c in p["cards"]]
    new_xp = next(c["xp"] for c in p["cards"] if c["id"] == POOL + 10)
    assert new_xp != old_xp
    assert p["projected"] == pytest.approx(before + new_xp - old_xp)
    assert p["base_grades"] != p["grades"] or p["plan"]["compare"]["grades"] == []
    new = next(c for c in p["cards"] if c["id"] == POOL + 10)
    assert new["was"] == "P9010" and new["original_id"] == USER + 10
    assert next(c for c in p["cards"] if c["id"] == USER + 1)["was"] is None


def test_app_sheet_actions_change_the_plan(env):
    at = run()
    act(at, {"type": "swap", "out_id": USER + 10, "in_id": POOL + 10})
    assert not at.exception
    p = payload(at)
    assert p["plan"]["n_changes"] == 1 and p["focus_id"] == POOL + 10
    act(at, {"type": "set_ft", "ft": 3})
    assert payload(at)["ft"] == 3
    act(at, {"type": "undo", "original_id": USER + 10})
    p = payload(at)
    assert p["plan"] is None and "P9010" in [c["name"] for c in p["cards"]]
    assert p["ft"] == 3                                            # undo keeps the estimate


def test_app_swap_error_reaches_the_sheet(env):
    at = run()
    act(at, {"type": "swap", "out_id": USER + 10, "in_id": POOL + 1})   # a GK for a FWD
    p = payload(at)
    assert p["error"] and p["plan"] is None and not at.error


def test_app_plan_resets_for_another_team(env):
    from fpl.plan import Move
    at = run()
    at.session_state["plan"] = plan_state([Move(USER + 10, POOL + 10)], team="999")
    at.run()
    assert payload(at)["plan"] is None


def test_app_plan_that_no_longer_applies_starts_again(env):
    from fpl.plan import Move
    at = run()
    at.session_state["plan"] = plan_state([Move(USER + 10, POOL + 1)])   # a GK for a FWD
    at.run()
    assert not at.exception
    p = payload(at)
    assert p["plan"] is None and p["error"] and at.session_state["plan"]["moves"] == []


def test_app_over_budget_plan_shows_not_errors(env):
    from fpl.plan import Move
    env.execute("UPDATE player_snapshot SET now_cost = 500 WHERE player_id = ?", (POOL + 15,))
    env.commit()
    at = run()
    at.session_state["plan"] = plan_state([Move(USER + 10, POOL + 15)])
    at.run()
    assert not at.exception and not at.error
    p = payload(at)
    assert p["bank"] < 0 and p["plan"]["bank"] == p["bank"]
    assert "P9115" in [c["name"] for c in p["cards"]]


def test_app_bench_suggestion_names_the_starter_it_replaces(env):
    s = sells(run())
    # P9014 is the bench MID; the starting MIDs tie on xp, so the first (P9006) makes way
    assert s["P9014"]["starts_instead_of"] == "P9006"
    assert not any(v["starts_instead_of"] for k, v in s.items() if k == "P9006")


def test_app_sees_refreshed_database_file(env):
    import os
    assert not run().warning
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    env.execute("UPDATE meta SET value = ? WHERE key = 'last_collected'", (old,))
    env.commit()
    path = env.execute("PRAGMA database_list").fetchone()["file"]
    later = os.path.getmtime(path) + 60
    os.utime(path, (later, later))      # a new data/fpl.db; the cache is not cleared
    assert "Player data may be out of date" in run().warning[0].value


def test_app_changes_use_free_transfers(env):
    from fpl.plan import Move
    at = run()
    s0 = sells(at)
    assert s0 and all(not v["hit"] for v in s0.values())
    opts = [o for c in payload(at)["cards"] for o in c["options"]]
    assert opts and all(o["hit"] == 0 for o in opts)
    at.session_state["plan"] = plan_state([Move(USER + 10, POOL + 10)], ft=1)
    at.run()
    s = sells(at)
    assert s and all(v["hit"] == 4 for v in s.values())
    p = payload(at)
    assert p["ft"] == 1 and p["plan"]["ft_used"] == 1 and p["plan"]["hit"] == 0
    cards = {c["id"]: c for c in p["cards"]}
    # selling another original costs a hit; replacing the IN player does not open a change
    assert all(o["hit"] == 4 for o in cards[USER + 1]["options"])
    assert all(o["hit"] == 0 for o in cards[POOL + 10]["options"])
    assert not any("test swap" in c.value for c in at.caption)


def test_app_card_options_name_the_starter(env):
    p = payload(run())
    bench_mid = next(c for c in p["cards"] if c["name"] == "P9014")
    assert bench_mid["options"] and bench_mid["options"][0]["starts_instead_of"] == "P9006"
    assert bench_mid["selling_price"] == pytest.approx(5.0)
    assert all(o["starts_instead_of"] is None
               for o in next(c for c in p["cards"] if c["name"] == "P9006")["options"])


def test_app_names_player_missing_from_db(env, monkeypatch):
    env.execute("DELETE FROM player WHERE player_id = ?", (USER + 15,))
    env.commit()
    monkeypatch.setattr(FakeApp, "entry_transfers", lambda self, tid: [
        {"event": 1, "element_in": USER + 15, "element_in_cost": 50}])
    at = run()
    assert not at.exception
    assert any(f"{USER + 15}" in w.value and "player data not loaded yet" in w.value
               for w in at.warning)


def _footer(env, one, three):
    env.execute("INSERT OR REPLACE INTO meta VALUES ('forecast_source_1gw', ?)", (one,))
    env.execute("INSERT OR REPLACE INTO meta VALUES ('forecast_source_3gw', ?)", (three,))
    env.commit()
    return " ".join(c.value for c in run().caption)


def test_app_footer_names_v1_model_source(env):
    foot = _footer(env, "model", "model")
    assert "this site's v1 model (next week) · this site's v1 model (3 weeks)" in foot
    assert "scaled by fixtures" not in foot


def test_app_footer_old_fpl_ep_setting_is_shown_as_v2(env):
    foot = _footer(env, "fpl_ep", "fpl_ep")
    assert "this site's v2 model (next week) · this site's v2 model (3 weeks)" in foot
    assert "FPL's own" not in foot


def test_app_footer_last5_avg_source(env):
    foot = _footer(env, "last5_avg", "model")
    assert "each player's recent average (next week) · this site's v1 model (3 weeks)" in foot


def test_app_footer_v2_source(env):
    foot = _footer(env, "model", "v2")
    assert "this site's v1 model (next week) · this site's v2 model (3 weeks)" in foot


def test_weakness_frame_xg_columns_1dp_and_leakiest_highlighted():
    from app import weakness_frame
    rows = [{"team": "A", "gk": 1.0, "def": 2.0, "mid": 3.0, "fwd": 4.0,
             "rank": {"gk": 1, "def": 2, "mid": 1, "fwd": 2},
             "xg": {"gk": 0.0, "def": 0.12, "mid": 0.55, "fwd": 0.9},
             "xg_rank": {"gk": 1, "def": 1, "mid": 2, "fwd": 2}},
            {"team": "B", "gk": 0.5, "def": 3.0, "mid": 2.0, "fwd": 5.0,
             "rank": {"gk": 2, "def": 1, "mid": 2, "fwd": 1},
             "xg": {"gk": None, "def": 0.04, "mid": 0.81, "fwd": 1.26},
             "xg_rank": {"gk": None, "def": 2, "mid": 1, "fwd": 1}}]
    sty = weakness_frame(rows)
    html = sty.to_html()
    assert ">0.1<" in html and ">0.8<" in html and ">1.3<" in html and ">–<" in html
    sty._compute()
    cols = list(sty.data.columns)
    lit = {(sty.data.index[r], cols[c]) for (r, c), css in sty.ctx.items() if css}
    assert lit == {("A", "GK"), ("B", "DEF"), ("A", "MID"), ("B", "FWD"),
                   ("A", "GK xG"), ("A", "DEF xG"), ("B", "MID xG"), ("B", "FWD xG")}


def test_app_junk_action_does_not_crash(env):
    at = run()
    for i, junk in enumerate(["swap", 5, {"type": "swap", "n": "x"},
                              {"type": "set_ft", "ft": "9" * 5000}]):
        at.session_state["sheet_action"] = junk if not isinstance(junk, dict) else {**junk, "n": i + 1}
        at.run()
        assert not at.exception


def test_app_stashed_action_dropped_on_fetch_error(env):
    FakeApp.error = FplApiError("down", status=503)
    at = run()
    at.session_state["sheet_action"] = {"type": "reset", "n": 1}
    at.run()
    assert "sheet_action" not in at.session_state


def test_relabel_plan_grades_uses_strip_labels():
    import app
    assert app.relabel_plan_grades(None) is None
    pl = {"compare": {"grades": [["midfield", "B", "A"], ["fixtures", "C", "B"],
                                 ["risk", "D", "C"], ["bench", "E", "D"]], "bank": [1, 2]}}
    out = app.relabel_plan_grades(pl)
    assert [g[0] for g in out["compare"]["grades"]] == [
        "Midfield", "Fixtures (next 5)", "Injury / rotation risk", "Bench"]
    assert out["compare"]["bank"] == [1, 2]
