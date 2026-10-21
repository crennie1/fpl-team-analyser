"""Analyse a user's squad: per-player colours and flags, grades and projection."""
from dataclasses import dataclass, field
from typing import Literal

from fpl.squad import Squad

AREAS = ("attack", "midfield", "defence", "fixtures", "risk", "bench", "projected")
NO_GRADE = "–"


@dataclass
class PlayerView:
    player_id: int
    name: str
    position: str
    club: str
    xp_next: float
    colour: Literal["green", "amber", "red"]
    flag: str | None
    is_starter: bool
    is_captain: bool


@dataclass
class Analysis:
    players: list
    grades: dict
    projected: float
    average_projected: float
    gw: int
    note: str | None
    missing: list = field(default_factory=list)   # squad player ids not in the database yet (not on the pitch)
    projected3: float = 0.0                       # starters' + captain's xp_next3 (next three gameweeks)


def colour_for(xp_next, chance_next):
    """Red below 2 xP or when FPL gives a 50% chance or less; amber below 4; else green."""
    if xp_next < 2 or (chance_next is not None and chance_next <= 50):
        return "red"
    return "amber" if xp_next < 4 else "green"


def _save_user_squad(conn, squad):
    conn.execute("DELETE FROM squad_pick WHERE squad_id = 'user'")
    conn.executemany(
        "INSERT INTO squad_pick (squad_id, player_id, slot, is_starter, is_captain) "
        "VALUES ('user', ?, ?, ?, ?)",
        [(p.player_id, p.slot, int(p.is_starter), int(p.is_captain)) for p in squad.picks])
    conn.commit()


def _player_views(conn):
    rows = conn.execute(
        "SELECT sp.player_id, pl.web_name, pl.position, t.short_name AS club, "
        "       COALESCE(x.xp_next, 0.0) AS xp_next, sn.status, sn.chance_next, sn.news, "
        "       sp.is_starter, sp.is_captain "
        "FROM squad_pick AS sp "
        "JOIN player AS pl ON pl.player_id = sp.player_id "
        "     AND pl.season = (SELECT value FROM meta WHERE key = 'current_season') "
        "JOIN team AS t ON t.season = pl.season AND t.team_id = pl.team_id "
        "LEFT JOIN xp_next_cache AS x ON x.player_id = sp.player_id "
        "LEFT JOIN v_latest_snapshot AS sn ON sn.player_id = sp.player_id "
        "WHERE sp.squad_id = 'user' ORDER BY sp.slot").fetchall()
    views = []
    for r in rows:
        flag = None
        if r["status"] is not None and r["status"] != "a":
            flag = r["news"] or f"Flagged by FPL (status {r['status']})"
        views.append(PlayerView(r["player_id"], r["web_name"], r["position"], r["club"],
                                r["xp_next"], colour_for(r["xp_next"], r["chance_next"]),
                                flag, bool(r["is_starter"]), bool(r["is_captain"])))
    return views


def analyse_squad(conn, squad: Squad) -> Analysis:
    """Store the squad as 'user', then read players, grades and projection from the views."""
    _save_user_squad(conn, squad)
    grades = {a: NO_GRADE for a in AREAS}
    for r in conn.execute("SELECT area, grade FROM v_squad_grades WHERE squad_id = 'user'"):
        grades[r["area"]] = r["grade"]
    projected = conn.execute(
        "SELECT projected, projected3 FROM v_squad_metrics WHERE squad_id = 'user'").fetchone()
    average = conn.execute(
        "SELECT AVG(m.projected) FROM v_squad_metrics AS m "
        "JOIN reference_squad AS r ON r.squad_id = m.squad_id "
        "WHERE r.season = (SELECT value FROM meta WHERE key = 'current_season')").fetchone()[0]
    players = _player_views(conn)
    shown = {p.player_id for p in players}
    return Analysis(players, grades,
                    projected[0] if projected else 0.0,
                    average if average is not None else 0.0,
                    squad.gw, squad.note,
                    [p.player_id for p in squad.picks if p.player_id not in shown],
                    projected[1] if projected else 0.0)
