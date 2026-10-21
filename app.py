"""Streamlit front end: Team ID in, pitch view, grades, suggestions and transfer planning out.

UI only. Every number comes from fpl.analyse / fpl.suggest (which read the SQL views).

Concurrency: the database is loaded once per server as immutable bytes
(st.cache_resource). Each script run deserialises its own private in-memory
connection from those bytes (about 10 ms), because analyse_squad writes the
'user' squad into squad_pick and sessions must never share that table.
"""
import hashlib
import importlib
import os
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def code_signature(root: Path, prefix: str = "fpl") -> str:
    """Short fingerprint of every .py under root/prefix and every .sql under root/prefix/sql."""
    pkg = root / prefix
    files = [*pkg.rglob("*.py"), *(pkg / "sql").glob("*.sql")]
    lines = []
    for f in files:
        if "__pycache__" in f.relative_to(pkg).parts:
            continue
        try:
            info = f.stat()
        except FileNotFoundError:   # deleted mid-pull: its absence changes the signature
            continue
        lines.append(f"{f.relative_to(root).as_posix()}:{info.st_mtime_ns}:{info.st_size}")
    return hashlib.sha1("\n".join(sorted(lines)).encode()).hexdigest()[:16]


def reload_if_code_changed(signature: str, modules: dict | None = None, state=sys,
                           prefix: str = "fpl") -> list[str]:
    """Unload every `prefix` module if the code signature differs from the recorded one.

    Streamlit's live update can keep an old fpl module loaded after a push (seen 21 Oct
    2026). Each run fingerprints the fpl code and SQL files and, if that differs from what
    the loaded modules were imported under (or this process never recorded one, e.g. after
    an update from older code), reloads every fpl module and clears the caches.
    Always records `signature` on `state`; returns the removed module names.
    """
    modules = sys.modules if modules is None else modules
    try:
        names = sorted(n for n in list(modules) if n == prefix or n.startswith(prefix + "."))
        if not names or getattr(state, "_fpl_code_signature", None) == signature:
            return []
        for n in names:
            modules.pop(n, None)
        return names
    finally:
        state._fpl_code_signature = signature


# Fingerprint taken BEFORE the imports: if files change while they import, the next run's
# signature differs and it reloads again. It is also part of every cache key below.
CODE_SIGNATURE = code_signature(Path(__file__).parent)
if os.environ.get("FPL_RELOAD_GUARD") != "0" and reload_if_code_changed(CODE_SIGNATURE):
    # cached results (the prepared database with its views, fetched squads) were built
    # by the old code, so they go too
    importlib.invalidate_caches()
    st.cache_data.clear()
    st.cache_resource.clear()

try:
    from fpl import api, cards, db, plan
    from fpl.analyse import analyse_squad
    from fpl.api import FplApiError
    from fpl.squad import SquadError, load_squad
    from fpl.suggest import options_for, suggest
    from fpl.ui.kits import KITS
finally:
    # recorded even when an import fails mid-push, so the next run compares against it
    sys._fpl_code_signature = CODE_SIGNATURE

STALE_AFTER = timedelta(hours=36)
API_DOWN = "FPL data is unavailable right now — try again in a few minutes."
GRADE_ROWS = [("attack", "Attack"), ("midfield", "Midfield"), ("defence", "Defence"),
              ("fixtures", "Fixtures (next 5)"), ("risk", "Injury / rotation risk"),
              ("bench", "Bench")]
# Two-way team sheet: draws the payload it is given and posts back the user's plan actions
TEAM_SHEET = components.declare_component(
    "team_sheet", path=str(Path(__file__).parent / "fpl" / "ui" / "team_sheet"))


def db_path() -> Path:
    return Path(os.environ.get("FPL_DB") or Path(__file__).parent / "data" / "fpl.db")


# ---------------------------------------------------------------- data access

@st.cache_resource(show_spinner="Loading player data…")
def _master_bytes(path: str, mtime: float, code: str) -> bytes:
    """Prepared database (views applied, forecast cache refreshed) as immutable bytes.

    `mtime` and `code` are only cache keys: a refreshed data/fpl.db or new fpl code
    (CODE_SIGNATURE) gets a new entry.
    """
    master = db.memory_copy(path)
    try:
        return master.serialize()
    finally:
        master.close()


def _session_from(path: str, mtime: float, code: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.deserialize(_master_bytes(path, mtime, code))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.register_functions(conn)
    return conn


def open_session_db() -> sqlite3.Connection:
    """A private writable in-memory copy for this script run."""
    path = str(db_path())
    return _session_from(path, os.path.getmtime(path), CODE_SIGNATURE)


@st.cache_data(show_spinner=False)
def cached_weakness(path: str, mtime: float, code: str) -> list[dict]:
    """weakness_table for one database file, computed once (about 0.4 s on the real data).

    `mtime` and `code` are only cache keys: a refreshed data/fpl.db or new fpl code
    gets a new entry.
    """
    conn = _session_from(path, mtime, code)
    try:
        return cards.weakness_table(conn)
    finally:
        conn.close()


def session_weakness() -> list[dict]:
    path = str(db_path())
    return cached_weakness(path, os.path.getmtime(path), CODE_SIGNATURE)


@st.cache_data(show_spinner=False)
def cached_pool(path: str, mtime: float, code: str) -> dict[str, list[dict]]:
    """replacement_pool for one database file, computed once.

    `mtime` and `code` are only cache keys: a refreshed data/fpl.db or new fpl code
    gets a new entry.
    """
    conn = _session_from(path, mtime, code)
    try:
        return cards.replacement_pool(conn)
    finally:
        conn.close()


def session_pool() -> dict[str, list[dict]]:
    path = str(db_path())
    return cached_pool(path, os.path.getmtime(path), CODE_SIGNATURE)


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


# ------------------------------------------------------------------ rendering

def weakness_frame(rows):
    """Styled dataframe: points conceded per match to each position, then xG conceded per
    match to it ("GK xG" ...), 1 dp, the leakiest team in each column highlighted."""
    cols = {"gk": "GK", "def": "DEF", "mid": "MID", "fwd": "FWD"}

    def frame(get):
        return pd.DataFrame([{"Team": r["team"], **{lbl: get(r, k) for k, lbl in cols.items()},
                              **{f"{lbl} xG": get(r, k, True) for k, lbl in cols.items()}}
                             for r in rows]).set_index("Team")
    df = frame(lambda r, k, xg=False: r["xg"][k] if xg else r[k])
    ranks = frame(lambda r, k, xg=False: r["xg_rank"][k] if xg else r["rank"][k])
    return df.style.format("{:.1f}", na_rep="–").apply(
        lambda _: ranks.map(lambda v: "background-color:#ff5c7a;color:#0b1020;font-weight:700"
                            if v == 1 else ""), axis=None)


FORECAST_WORDS = {"fpl_ep": "FPL's own predictions",
                  "model": "this site's v1 model",
                  "v2": "this site's v2 model"}


def show_footer(meta):
    one = meta.get("forecast_source_1gw") or meta.get("forecast_source")
    three = meta.get("forecast_source_3gw") or one
    word = lambda k: FORECAST_WORDS.get(k, "unknown")   # noqa: E731
    # the 3-week fpl_ep number is FPL's one-week prediction scaled by the fixtures (R20)
    word3 = word(three) + (" scaled by fixtures" if three == "fpl_ep" else "")
    url = repo_url()
    text = f"Forecast: {word(one)} (next week) · {word3} (3 weeks)"
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

def on_sheet_action():
    """Team-sheet callback: runs before the rerun; the action is applied in plan_state()."""
    st.session_state["sheet_action"] = st.session_state.get("team_sheet")


def relabel_plan_grades(summary):
    """The plan summary with grade keys swapped for the labels the grade strip shows."""
    if not summary:
        return summary
    labels = dict(GRADE_ROWS)
    grades = [[labels.get(k, k), a, b] for k, a, b in summary["compare"]["grades"]]
    return {**summary, "compare": {**summary["compare"], "grades": grades}}


def plan_state(conn, team, base, fresh) -> dict:
    """This session's plan for `team`, with any action just posted from the team sheet applied.

    A new team ID or pressing Analyse starts again from the fetched squad.
    """
    ss = st.session_state
    state = ss.get("plan")
    if fresh or state is None or state["team"] != team:
        state = {"team": team, "moves": [], "ft": base.free_transfers, "last_n": 0,
                 "error": None, "focus_id": None}
    action = ss.pop("sheet_action", None)
    if isinstance(action, dict):
        state = plan.apply_action(state, action, base, conn)
    ss["plan"] = state
    return state


def card_extras(conn, base, current, names, ft) -> dict:
    """Per squad player: selling price, the 👍 replacements and, for a player brought in by
    the plan, the original player he replaced."""
    was = {in_id: out_id for out_id, in_id in plan.changes(base, current)}
    extras = {}
    for p in current.picks:
        extras[p.player_id] = {
            "selling_price": p.selling_price / 10,
            "options": [{"id": o.in_id, "gain3": o.gain3,
                         "hit": plan.extra_hit(base, current, p.player_id, o.in_id, ft),
                         "starts_instead_of": names.get(o.starts_instead)}
                        for o in options_for(conn, current, p.player_id)],
            "was": names.get(was.get(p.player_id)), "original_id": was.get(p.player_id)}
    return extras


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
            st.caption("Points conceded per match to each position over the last 6 gameweeks, "
                       "then the xG (expected goals) conceded per match to that position. "
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
        st.session_state.pop("sheet_action", None)   # don't let a stale click replay later
        st.error(str(exc))
        return
    except FplApiError:
        st.session_state.pop("sheet_action", None)
        st.error(API_DOWN)
        return

    state = plan_state(conn, team, base, fresh)
    try:
        current = plan.build(base, state["moves"], conn)
    except SquadError as exc:   # the fetched squad or the data changed under the plan
        state = st.session_state["plan"] = {**state, "moves": [], "error": str(exc)}
        current = base
    ft = state["ft"]
    n_changes = len(plan.changes(base, current))
    # base first, then the plan, so squad_pick is left holding the plan
    base_analysis = analyse_squad(conn, base)
    analysis = analyse_squad(conn, current) if state["moves"] else base_analysis
    # each change (a player not in the fetched squad) uses one free transfer
    suggestions = suggest(conn, replace(current, free_transfers=max(0, ft - n_changes)))

    st.markdown(f"**Analysing your GW{analysis.gw} squad**")
    if analysis.note:
        st.info(analysis.note)
    if analysis.missing:
        ids = ", ".join(map(str, analysis.missing))
        st.warning(f"Not shown: player {ids} — player data not loaded yet, "
                   f"try again after the next refresh.")

    names = {pv.player_id: pv.name for pv in [*base_analysis.players, *analysis.players]}
    prices = {p.player_id: p.selling_price / 10 for p in [*base.picks, *current.picks]}
    payload = {
        "cards": cards.player_cards(conn, analysis, suggestions, weakness=session_weakness(),
                                    extras=card_extras(conn, base, current, names, ft)),
        "grades": {label: analysis.grades.get(key, "–") for key, label in GRADE_ROWS},
        "base_grades": {label: base_analysis.grades.get(key, "–") for key, label in GRADE_ROWS},
        "projected": analysis.projected, "average": analysis.average_projected,
        "kits": KITS, "pool": session_pool(),
        "plan": relabel_plan_grades(
            plan.summary(base, current, base_analysis, analysis, names, prices, ft)),
        "ft": ft, "bank": round(current.bank / 10, 1),
        "focus_id": state["focus_id"], "error": state["error"],
        "n": state["last_n"]}   # the page numbers its next action after this one
    st.session_state["team_payload"] = payload
    TEAM_SHEET(payload=payload, key="team_sheet", default=None, on_change=on_sheet_action)
    if not suggestions:
        st.write("No transfer clearly worth making this week.")


if __name__ == "__main__":
    main()
