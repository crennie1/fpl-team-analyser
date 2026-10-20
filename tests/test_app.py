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
    # swap targets need fixtures: with no fixture in next_gw the forecast falls back to the model (R20)
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
    """The JSON the component page was built from (first iframe element)."""
    import json
    import re
    frames = at.get("iframe")
    assert len(frames) == 1
    return json.loads(re.search(r"const DATA = (.*?);\n", frames[0].proto.srcdoc, re.S).group(1))


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
    assert at.expander[0].label == "Edit squad"
    assert at.tabs[0].label == "Your team"


def test_app_weakness_tab(env):
    at = run()
    assert at.tabs[1].label == "Opponent weaknesses"
    df = at.dataframe[0].value
    assert list(df.columns) == ["GK", "DEF", "MID", "FWD"]
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
    assert "official FPL API" in foot and "FPL's own predictions" in foot
    assert "(next week)" in foot and "(3 weeks)" in foot
    assert "https://github.com/example/fpl/blob/main/reports/backtest.md" in foot


def test_app_swap_recalculates(env):
    at = run()
    before = payload(at)["projected"]
    at.selectbox(key="swap_out").select(USER + 10)       # a starting FWD, xp 4
    at.run()
    at.selectbox(key="swap_in").select(POOL + 10)        # FWD with xp 15
    at.run()
    at.button(key="apply_swap").click().run()
    assert not at.exception
    after = payload(at)["projected"]
    assert after == pytest.approx(before + 11)
    assert "P9110" in [c["name"] for c in payload(at)["cards"]]


def test_app_swap_error_shown(env):
    at = run()
    at.selectbox(key="swap_out").select(USER + 10)
    at.run()
    at.selectbox(key="swap_in").select(POOL + 15)        # FWD on team 8: fine
    at.run()
    env.execute("UPDATE player_snapshot SET now_cost = 500 WHERE player_id = ?", (POOL + 15,))
    env.commit()
    st.cache_resource.clear()
    at.button(key="apply_swap").click().run()
    assert any("Over budget" in e.value for e in at.error)


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


def test_app_test_swaps_use_up_free_transfers(env):
    at = run()
    s0 = sells(at)
    assert s0 and all(not v["hit"] for v in s0.values())
    at.selectbox(key="swap_out").select(USER + 10)
    at.run()
    at.selectbox(key="swap_in").select(POOL + 10)
    at.run()
    at.button(key="apply_swap").click().run()
    caps = " ".join(c.value for c in at.caption)
    assert "Your 1 test swap uses 1 free transfer, so these assume 0 free transfers left." in caps
    s = sells(at)
    assert s and all(v["hit"] == 4 for v in s.values())
    assert at.number_input(key=f"ft_{TEAM_ID}").value == 1     # the user's own estimate stays


def test_app_names_player_missing_from_db(env, monkeypatch):
    env.execute("DELETE FROM player WHERE player_id = ?", (USER + 15,))
    env.commit()
    monkeypatch.setattr(FakeApp, "entry_transfers", lambda self, tid: [
        {"event": 1, "element_in": USER + 15, "element_in_cost": 50}])
    at = run()
    assert not at.exception
    assert any(f"{USER + 15}" in w.value and "player data not loaded yet" in w.value
               for w in at.warning)
