"""Streamlit front end: Team ID in, pitch view, grades, suggestions and squad editing out.

UI only. Every number comes from fpl.analyse / fpl.suggest (which read the SQL views).

Concurrency: the database is loaded once per server as immutable bytes
(st.cache_resource). Each script run deserialises its own private in-memory
connection from those bytes (about 10 ms), because analyse_squad writes the
'user' squad into squad_pick and sessions must never share that table.
"""
import json
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from fpl import api, cards, db
from fpl.analyse import analyse_squad
from fpl.api import FplApiError
from fpl.squad import SquadError, load_squad, swap
from fpl.suggest import suggest
from fpl.ui.kits import KITS

STALE_AFTER = timedelta(hours=36)
API_DOWN = "FPL data is unavailable right now — try again in a few minutes."
GRADE_ROWS = [("attack", "Attack"), ("midfield", "Midfield"), ("defence", "Defence"),
              ("fixtures", "Fixtures (next 5)"), ("risk", "Injury / rotation risk"),
              ("bench", "Bench")]
TEMPLATE = Path(__file__).parent / "fpl" / "ui" / "team_view.html"
VIEW_HEIGHT = 1100


def db_path() -> Path:
    return Path(os.environ.get("FPL_DB") or Path(__file__).parent / "data" / "fpl.db")


# ---------------------------------------------------------------- data access

@st.cache_resource(show_spinner="Loading player data…")
def _master_bytes(path: str, mtime: float) -> bytes:
    """Prepared database (views applied, forecast cache refreshed) as immutable bytes.

    `mtime` is only a cache key: a refreshed data/fpl.db gets a new entry.
    """
    master = db.memory_copy(path)
    try:
        return master.serialize()
    finally:
        master.close()


def _session_from(path: str, mtime: float) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.deserialize(_master_bytes(path, mtime))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.register_functions(conn)
    return conn


def open_session_db() -> sqlite3.Connection:
    """A private writable in-memory copy for this script run."""
    path = str(db_path())
    return _session_from(path, os.path.getmtime(path))


@st.cache_data(show_spinner=False)
def cached_weakness(path: str, mtime: float) -> list[dict]:
    """weakness_table for one database file, computed once (about 0.4 s on the real data).

    `mtime` is only a cache key: a refreshed data/fpl.db gets a new entry.
    """
    conn = _session_from(path, mtime)
    try:
        return cards.weakness_table(conn)
    finally:
        conn.close()


def session_weakness() -> list[dict]:
    path = str(db_path())
    return cached_weakness(path, os.path.getmtime(path))


@st.cache_data(ttl=600, show_spinner="Fetching your squad from FPL…")
def fetch_squad(team_id: str, _conn):
    """Network part: cached ten minutes per team ID. Errors are not cached."""
    return load_squad(api.FplClient(), _conn, team_id)


def get_meta(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def repo_url() -> str | None:
    url = os.environ.get("REPO_URL")
    if not url:
        try:
            url = st.secrets.get("REPO_URL")
        except Exception:   # no secrets file configured
            url = None
    return url.rstrip("/") if url else None


def candidates(conn, position, squad_ids):
    """Players of `position` not already in the squad, by name, for the 'replace with' box."""
    marks = ",".join("?" * len(squad_ids)) or "-1"
    return conn.execute(
        f"SELECT p.player_id, p.web_name, t.short_name AS club, s.now_cost "
        f"FROM player AS p "
        f"JOIN team AS t ON t.season = p.season AND t.team_id = p.team_id "
        f"JOIN v_latest_snapshot AS s ON s.player_id = p.player_id "
        f"WHERE p.season = (SELECT value FROM meta WHERE key = 'current_season') "
        f"  AND p.position = ? AND p.player_id NOT IN ({marks}) "
        f"ORDER BY p.web_name COLLATE NOCASE, p.player_id", [position, *squad_ids]).fetchall()


# ------------------------------------------------------------------ rendering

def team_view_html(payload: dict) -> str:
    """The component page: the template with the payload JSON in place of /*DATA*/.

    <, > and & are escaped as unicode so no player name can close the script tag.
    """
    data = (json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))
    return TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", data)


def weakness_frame(rows):
    """Styled dataframe: positions as columns, 1 dp, the leakiest team per position highlighted."""
    cols = {"gk": "GK", "def": "DEF", "mid": "MID", "fwd": "FWD"}
    df = pd.DataFrame([{"Team": r["team"], **{lbl: r[k] for k, lbl in cols.items()}} for r in rows])
    ranks = pd.DataFrame([{"Team": r["team"], **{lbl: r["rank"][k] for k, lbl in cols.items()}}
                          for r in rows])
    df = df.set_index("Team")
    ranks = ranks.set_index("Team")
    return df.style.format("{:.1f}", na_rep="–").apply(
        lambda _: ranks.map(lambda v: "background-color:#ff5c7a;color:#0b1020;font-weight:700"
                            if v == 1 else ""), axis=None)


FORECAST_WORDS = {"fpl_ep": "FPL's own predictions",
                  "model": "FPL's own predictions scaled by fixtures",
                  "v2": "this site's v2 model"}


def show_footer(meta):
    one = meta.get("forecast_source_1gw") or meta.get("forecast_source")
    three = meta.get("forecast_source_3gw") or one
    word = lambda k: FORECAST_WORDS.get(k, "unknown")   # noqa: E731
    url = repo_url()
    text = f"Forecast: {word(one)} (next week) · {word(three)} (3 weeks)"
    forecast = f"[{text}]({url}/blob/main/reports/backtest.md)" if url else text
    st.caption(f"Data: official FPL API · last updated {meta.get('last_collected', 'unknown')} · "
               f"{forecast}")


def show_stale_warning(meta):
    last = meta.get("last_collected")
    try:
        when = datetime.fromisoformat(last)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        stale = datetime.now(timezone.utc) - when > STALE_AFTER
    except (TypeError, ValueError):
        stale = True
    if stale:
        st.warning(f"Player data may be out of date (last updated {last or 'unknown'})")


# ---------------------------------------------------------------------- state

def request_swap():
    """Button callback: runs before the rerun; the swap itself is applied in main()."""
    ss = st.session_state
    ss["pending_swap"] = (ss.get("swap_out"), ss.get("swap_in"))


def current_squad(conn, team, base, fresh):
    """The squad being analysed: the fetched one plus any edits made this session."""
    ss = st.session_state
    if fresh or ss.get("edit_team") != team or "edited" not in ss:
        ss["edit_team"], ss["edited"] = team, base
        ss.pop("swap_error", None)
    pending = ss.pop("pending_swap", None)
    if pending and None not in pending:
        try:
            ss["edited"] = swap(ss["edited"], pending[0], pending[1], conn)
            ss.pop("swap_error", None)
        except SquadError as exc:
            ss["swap_error"] = str(exc)
    return ss["edited"]


# ----------------------------------------------------------------------- main

def main():
    st.set_page_config(page_title="FPL Team Analyser", page_icon="⚽", layout="wide")
    st.title("FPL Team Analyser")
    st.caption("Enter your public FPL team ID to see how your squad looks for the next gameweek.")

    with st.form("team_form", border=False):
        c_in, c_btn = st.columns([4, 1], vertical_alignment="bottom")
        text = c_in.text_input("Team ID", value=st.query_params.get("team", ""), key="team_id",
                               placeholder="e.g. 1234567")
        fresh = c_btn.form_submit_button("Analyse", use_container_width=True)
    if fresh:
        st.query_params["team"] = text.strip()
    team = st.query_params.get("team", "").strip()

    conn = open_session_db()
    try:
        meta = get_meta(conn)
        show_stale_warning(meta)
        team_tab, weak_tab = st.tabs(["Your team", "Opponent weaknesses"])
        with team_tab:
            if not team:
                st.info("Find your team ID in the address of your FPL points page: "
                        "fantasy.premierleague.com/entry/**1234567**/event/1")
            else:
                render_team(conn, team, fresh)
        with weak_tab:
            st.caption("Points conceded per match to each position over the last 6 gameweeks. "
                       "The leakiest team in each column is highlighted.")
            st.dataframe(weakness_frame(session_weakness()), width="stretch",
                         height=740)
        show_footer(meta)
    finally:
        conn.close()


def render_team(conn, team, fresh):
    try:
        base = fetch_squad(team, conn)
    except SquadError as exc:
        st.error(str(exc))
        return
    except FplApiError:
        st.error(API_DOWN)
        return

    squad = current_squad(conn, team, base, fresh)
    ft = int(st.session_state.get(f"ft_{team}", squad.free_transfers))
    # each test swap (a player not in the fetched squad) uses one free transfer
    edits = len({p.player_id for p in squad.picks} - {p.player_id for p in base.picks})
    ft_left = max(0, ft - edits)
    squad_ft = replace(squad, free_transfers=ft_left)
    analysis = analyse_squad(conn, squad)
    suggestions = suggest(conn, squad_ft)   # leaves the user's squad in place

    st.markdown(f"**Analysing your GW{analysis.gw} squad**")
    if analysis.note:
        st.info(analysis.note)
    if analysis.missing:
        ids = ", ".join(map(str, analysis.missing))
        st.warning(f"Not shown: player {ids} — player data not loaded yet, "
                   f"try again after the next refresh.")

    if edits:
        st.caption(f"Your {edits} test swap{'s' if edits > 1 else ''} "
                   f"use{'' if edits > 1 else 's'} {edits} free transfer{'s' if edits > 1 else ''}, "
                   f"so these assume {ft_left} free transfer{'' if ft_left == 1 else 's'} left.")
    payload = {
        "cards": cards.player_cards(conn, analysis, suggestions, weakness=session_weakness()),
        "grades": {label: analysis.grades.get(key, "–") for key, label in GRADE_ROWS},
        "projected": analysis.projected, "average": analysis.average_projected,
        "kits": KITS}
    components.html(team_view_html(payload), height=VIEW_HEIGHT, scrolling=True)
    if not suggestions:
        st.write("No transfer clearly worth making this week.")

    with st.expander("Edit squad"):
        edit_squad(conn, team, analysis, squad)


def edit_squad(conn, team, analysis, squad):
    ss = st.session_state
    st.number_input("Free transfers", min_value=0, max_value=5, value=squad.free_transfers,
                    step=1, key=f"ft_{team}",
                    help="Estimated from your transfer history; change it if it is wrong. "
                         "Test swaps below are taken off this for the suggestions.")
    by_id = {p.player_id: p for p in analysis.players}
    out_id = st.selectbox("Player to sell", list(by_id), key="swap_out",
                          format_func=lambda i: f"{by_id[i].name} ({by_id[i].position}, "
                                                f"{by_id[i].club})")
    cands = candidates(conn, by_id[out_id].position, list(by_id))
    names = {c["player_id"]: f"{c['web_name']} ({c['club']}, £{c['now_cost'] / 10:.1f}m)"
             for c in cands}
    st.selectbox("Replace with (type to search)", list(names), key="swap_in",
                 format_func=names.get)
    st.button("Apply swap", key="apply_swap", on_click=request_swap)
    st.caption(f"Bank: £{squad.bank / 10:.1f}m")
    if ss.get("swap_error"):
        st.error(ss["swap_error"])


if __name__ == "__main__":
    main()
