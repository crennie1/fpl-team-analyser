"""Streamlit front end: Team ID in, pitch view, grades, suggestions and squad editing out.

UI only. Every number comes from fpl.analyse / fpl.suggest (which read the SQL views).

Concurrency: the database is loaded once per server as immutable bytes
(st.cache_resource). Each script run deserialises its own private in-memory
connection from those bytes (about 10 ms), because analyse_squad writes the
'user' squad into squad_pick and sessions must never share that table.
"""
import html
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from fpl import api, db
from fpl.analyse import analyse_squad
from fpl.api import FplApiError
from fpl.squad import SquadError, load_squad, swap
from fpl.suggest import suggest

STALE_AFTER = timedelta(hours=36)
API_DOWN = "FPL data is unavailable right now — try again in a few minutes."
GRADE_ROWS = [("attack", "Attack"), ("midfield", "Midfield"), ("defence", "Defence"),
              ("fixtures", "Fixtures (next 5)"), ("risk", "Injury / rotation risk"),
              ("bench", "Bench")]
CHIP_STYLE = {
    "green": "background:#1b5e20;border:1px solid #fff;color:#fff",
    "amber": "background:#f9a825;border:1px solid #f9a825;color:#000",
    "red": "background:#c62828;border:1px solid #c62828;color:#fff",
}
AREA_NAMES = {"attack": "Attack", "midfield": "Midfield", "defence": "Defence"}


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


def open_session_db() -> sqlite3.Connection:
    """A private writable in-memory copy for this script run."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    path = str(db_path())
    conn.deserialize(_master_bytes(path, os.path.getmtime(path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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

def chip(p) -> str:
    label = html.escape(p.name) + (" (C)" if p.is_captain else "") + (" ✚" if p.flag else "")
    title = f' title="{html.escape(p.flag, quote=True)}"' if p.flag else ""
    return (f'<span{title} style="{CHIP_STYLE[p.colour]};display:inline-block;padding:3px 7px;'
            f'margin:3px;border-radius:4px;white-space:nowrap;font-size:14px">'
            f'{label} {p.xp_next:.1f}</span>')


def pitch_html(players) -> str:
    rows = []
    for pos in ("FWD", "MID", "DEF", "GK"):
        chips = "".join(chip(p) for p in players if p.is_starter and p.position == pos)
        rows.append(f"<div>{chips}</div>")
    bench = "".join(chip(p) for p in players if not p.is_starter)
    return (
        '<div style="background:#2e7d32;border-radius:8px;padding:12px 6px;color:#fff;'
        'text-align:center;line-height:2.1">' + "".join(rows) +
        '<div style="border-top:1px dashed rgba(255,255,255,.5);margin-top:8px;padding-top:6px">'
        '<div style="font-size:12px;opacity:.85;letter-spacing:.05em">BENCH</div>'
        f'<div>{bench}</div></div>'
        '<div style="font-size:11px;opacity:.85;line-height:1.4;margin-top:8px">'
        'Number = expected points next gameweek · green good · amber weak · red problem · '
        '✚ = flagged by FPL (hover for news) · (C) = captain</div></div>')


def grades_html(grades) -> str:
    cells = []
    for key, label in GRADE_ROWS:
        g = grades.get(key, "–")
        colour = "#c62828" if g in ("D", "E") else "inherit"
        cells.append(f"<span>{label}</span><b style='color:{colour}'>{html.escape(g)}</b>")
    return ('<div style="display:grid;grid-template-columns:1fr auto;gap:6px 12px">'
            + "".join(cells) + "</div>")


def format_suggestion(n, s) -> str:
    area, before, after = s.grade_change
    hit = f" (−{s.hit} hit)" if s.hit else ""
    starts = f" (starts instead of {s.starts_instead})" if s.starts_instead else ""
    return (f"{n}. {s.out_name} → {s.in_name}{starts} · +{s.gain3:.1f} pts over the next 3 GWs · "
            f"{AREA_NAMES.get(area, area.title())} {before} → {after}{hit}")


def show_footer(meta):
    source = {"fpl_ep": "FPL's own predictions", "model": "this site's model"}.get(
        meta.get("forecast_source"), "unknown")
    url = repo_url()
    forecast = (f"[Forecast: {source}]({url}/blob/main/reports/backtest.md)" if url
                else f"Forecast: {source}")
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
        if not team:
            st.info("Find your team ID in the address of your FPL points page: "
                    "fantasy.premierleague.com/entry/**1234567**/event/1")
        else:
            render_team(conn, team, fresh)
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

    left, right = st.columns([2, 1])
    with left:
        st.markdown(pitch_html(analysis.players), unsafe_allow_html=True)
    with right:
        st.markdown("**Team grades**")
        st.markdown(grades_html(analysis.grades), unsafe_allow_html=True)
        st.markdown(f"**Projected:** {analysis.projected:.1f} pts  \n"
                    f"<span style='opacity:.7'>average manager: "
                    f"{analysis.average_projected:.1f}</span>", unsafe_allow_html=True)

    st.markdown("**Suggested moves**")
    if edits:
        st.caption(f"Your {edits} test swap{'s' if edits > 1 else ''} "
                   f"use{'' if edits > 1 else 's'} {edits} free transfer{'s' if edits > 1 else ''}, "
                   f"so these assume {ft_left} free transfer{'' if ft_left == 1 else 's'} left.")
    if suggestions:
        st.caption("Best single moves — each is checked on its own against your current "
                   "squad, so pick one rather than making all of them.")
        for n, s in enumerate(suggestions, start=1):
            st.markdown(format_suggestion(n, s))
    else:
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


main()
