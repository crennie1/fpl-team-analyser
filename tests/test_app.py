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


def test_app_renders_grades_and_projection(env):
    at = run()
    assert not at.exception
    body = text(at)
    for label in ("Attack", "Midfield", "Defence", "Fixtures (next 5)",
                  "Injury / rotation risk", "Bench"):
        assert label in body
    assert body.count("<b style='color:") == 6          # one grade per row
    assert "Projected:" in body and "average manager" in body
    assert "Analysing your GW5 squad" in body
    assert "P9009 (C)" in body                           # captain marked on the pitch
    assert at.expander[0].label == "Edit squad"


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
    assert "Projected:" in text(at)


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
    assert "https://github.com/example/fpl/blob/main/reports/backtest.md" in foot


def test_app_swap_recalculates(env):
    at = run()
    before = text(at).split("Projected:**")[1].split("pts")[0]
    at.selectbox(key="swap_out").select(USER + 10)       # a starting FWD, xp 4
    at.run()
    at.selectbox(key="swap_in").select(POOL + 10)        # FWD with xp 15
    at.run()
    at.button(key="apply_swap").click().run()
    assert not at.exception
    after = text(at).split("Projected:**")[1].split("pts")[0]
    assert float(after) == pytest.approx(float(before) + 11)
    assert "P9110" in text(at)


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
