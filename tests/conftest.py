import json
from pathlib import Path

import pytest

from fpl import db

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Serves recorded JSON; no network."""

    def __init__(self):
        self.live_calls = []

    def bootstrap(self):
        return json.loads((FIXTURES / "bootstrap.json").read_text())

    def fixtures(self):
        return json.loads((FIXTURES / "fixtures.json").read_text())

    def event_live(self, gw):
        self.live_calls.append(gw)
        return json.loads((FIXTURES / f"event_live_{gw}.json").read_text())


@pytest.fixture
def tmp_db(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.apply_sql(conn, "schema.sql")
    yield conn
    conn.close()


@pytest.fixture
def fake_client():
    return FakeClient()


def _insert(conn, table, rows):
    """Insert dict rows into `table` (all dicts must share the same keys)."""
    cols = list(rows[0])
    conn.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in rows],
    )


@pytest.fixture
def db_with_sample(tmp_db):
    """Small hand-built database. Current season 2026-27, next_gw 6.

    Players (2026-27):
      1 A  MID team 1  played gws 1-5: 90 min, 4 pts each        -> 4.0 pts/90, start_prob 1
      2 B  MID team 1  played gws 1-5: 45 min, 1 pt each         -> start_prob 0.5
      3 C  FWD team 2  played gws 1-5: 90 min, 2 pts each        -> chance_next 25 in snapshot
      4 D  DEF team 3  gws 1-3: 90 min, 2 pts; gws 4-5: 90 min, 12 pts (form jumps at gw 4)
      5 E  MID team 1  new signing, no player_gw rows
    Fixtures (all FDR 3, so the FDR multiplier is 1 for them):
      gw 6: team1 v team4, team2 v team3 (team 3 plays once)
      gw 7: team1 v team4, team3 v team4 twice (team 3 double, team 2 blank)
      gw 8: team1 v team4
    Backtest season 2025-26 supplies the FDR multipliers: MID scores 3, 2, 1
    pts/90 at FDR 2, 3, 4 (equal minutes); DEF and FWD score evenly at FDR 3.
    """
    conn = tmp_db
    _insert(conn, "meta", [
        {"key": "next_gw", "value": "6"},
        {"key": "current_season", "value": "2026-27"},
        {"key": "backtest_season", "value": "2025-26"},
    ])
    cur, old = "2026-27", "2025-26"
    _insert(conn, "player", [
        {"season": cur, "player_id": 1, "web_name": "A", "team_id": 1, "position": "MID"},
        {"season": cur, "player_id": 2, "web_name": "B", "team_id": 1, "position": "MID"},
        {"season": cur, "player_id": 3, "web_name": "C", "team_id": 2, "position": "FWD"},
        {"season": cur, "player_id": 4, "web_name": "D", "team_id": 3, "position": "DEF"},
        {"season": cur, "player_id": 5, "web_name": "E", "team_id": 1, "position": "MID"},
        {"season": old, "player_id": 101, "web_name": "OldMid", "team_id": 1, "position": "MID"},
        {"season": old, "player_id": 102, "web_name": "OldDef", "team_id": 1, "position": "DEF"},
        {"season": old, "player_id": 103, "web_name": "OldFwd", "team_id": 1, "position": "FWD"},
    ])

    # Current-season fixtures: gws 1-5 are past (finished), 6-8 are upcoming.
    fixtures, fid = [], 0
    def add_fixture(gw, h, a, finished=0):
        nonlocal fid
        fid += 1
        fixtures.append({"season": cur, "fixture_id": fid, "gw": gw, "team_h": h, "team_a": a,
                         "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": finished})
    for gw in range(1, 6):
        add_fixture(gw, 1, 4, 1)
        add_fixture(gw, 2, 3, 1)
    add_fixture(6, 1, 4); add_fixture(6, 2, 3)
    add_fixture(7, 1, 4); add_fixture(7, 3, 4); add_fixture(7, 4, 3)
    add_fixture(8, 1, 4)
    add_fixture(8, 2, 3)
    # the backtest season only needs gameweek numbers for the as_of grid
    fixtures.append({"season": old, "fixture_id": 1, "gw": 1, "team_h": 1, "team_a": 2,
                     "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": 1})
    _insert(conn, "fixture", fixtures)

    # Current-season history (gws 1-5); fixture_id 1 or 2 is the matching fixture.
    def gw_row(gw, pid, minutes, pts, fixture_id, fdr=3):
        return {"season": cur, "gw": gw, "player_id": pid, "fixture_id": fixture_id,
                "minutes": minutes, "total_points": pts, "was_home": 1,
                "opponent_team": 4, "fdr": fdr, "ep_pre": None}
    rows = []
    for gw in range(1, 6):
        f_team1, f_team2 = (gw - 1) * 2 + 1, (gw - 1) * 2 + 2
        rows += [
            gw_row(gw, 1, 90, 4, f_team1),
            gw_row(gw, 2, 45, 1, f_team1),
            gw_row(gw, 3, 90, 2, f_team2),
            gw_row(gw, 4, 90, 2 if gw <= 3 else 12, f_team2),
        ]
    # Backtest season: MID 3/2/1 pts per 90 at FDR 2/3/4; DEF, FWD flat at FDR 3.
    for n, (fdr, pts) in enumerate([(2, 3), (3, 2), (4, 1)], start=1):
        rows.append({"season": old, "gw": n, "player_id": 101, "fixture_id": 1, "minutes": 90,
                     "total_points": pts, "was_home": 1, "opponent_team": 2, "fdr": fdr, "ep_pre": None})
    rows.append({"season": old, "gw": 1, "player_id": 102, "fixture_id": 1, "minutes": 90,
                 "total_points": 2, "was_home": 1, "opponent_team": 2, "fdr": 3, "ep_pre": None})
    rows.append({"season": old, "gw": 1, "player_id": 103, "fixture_id": 1, "minutes": 90,
                 "total_points": 2, "was_home": 1, "opponent_team": 2, "fdr": 3, "ep_pre": None})
    _insert(conn, "player_gw", rows)

    def snap(pid, chance, ep):
        return {"season": cur, "gw": 6, "player_id": pid, "collected_at": "2026-10-19T12:00:00",
                "status": "a", "chance_next": chance, "ep_next": ep, "now_cost": 80,
                "selected_by_percent": 10.0}
    _insert(conn, "player_snapshot", [snap(1, None, 5.5), snap(2, None, 1.0),
                                      snap(3, 25, 0.5), snap(4, None, 6.0)])
    conn.commit()
    db.apply_views(conn)
    return conn
