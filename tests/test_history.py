from pathlib import Path

from fpl import history

FIX = Path(__file__).parent / "fixtures"


def _load(conn, season="2025-26"):
    return history.load(
        conn, season,
        FIX / "vaastav_merged_gw.csv", FIX / "vaastav_fixtures.csv", FIX / "vaastav_teams.csv",
    )


def test_history_maps_positions(tmp_db):
    _load(tmp_db)
    got = dict(tmp_db.execute("SELECT player_id, position FROM player").fetchall())
    assert got == {502: "GK", 541: "DEF", 612: "MID", 310: "FWD", 817: "FWD"}
    assert history.POSITIONS["GKP"] == "GK"


def test_history_ep_pre_from_xP(tmp_db):
    _load(tmp_db)
    ep = tmp_db.execute(
        "SELECT ep_pre FROM player_gw WHERE player_id = 612 AND gw = 1"
    ).fetchone()[0]
    assert ep == 2.6


def test_history_fdr_from_fixtures(tmp_db):
    _load(tmp_db)
    away = tmp_db.execute(  # West Ham away at Sunderland: team_a_difficulty
        "SELECT fdr FROM player_gw WHERE player_id = 612 AND fixture_id = 5"
    ).fetchone()[0]
    home = tmp_db.execute(  # Sunderland at home: team_h_difficulty
        "SELECT fdr FROM player_gw WHERE player_id = 541 AND fixture_id = 5"
    ).fetchone()[0]
    assert (away, home) == (3, 2)


def test_history_double_gw_two_rows(tmp_db):
    n = _load(tmp_db)
    rows = tmp_db.execute(
        "SELECT fixture_id, was_home, fdr FROM player_gw"
        " WHERE player_id = 817 AND gw = 26 ORDER BY fixture_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(257, 0, 3), (310, 1, 4)]
    assert n == 6


def test_history_records_season_and_is_rerunnable(tmp_db):
    _load(tmp_db)
    _load(tmp_db)
    assert tmp_db.execute(
        "SELECT value FROM meta WHERE key = 'backtest_season'"
    ).fetchone()[0] == "2025-26"
    assert tmp_db.execute("SELECT COUNT(*) FROM player_gw").fetchone()[0] == 6


def test_history_all_zero_xP_gameweek_is_null(tmp_db, tmp_path):
    lines = (FIX / "vaastav_merged_gw.csv").read_text().splitlines()
    hdr = lines[0].split(",")
    base = dict(zip(hdr, lines[1].split(",")))

    def row(gw, xp, el):
        d = dict(base, GW=str(gw), xP=str(xp), element=str(el))
        return ",".join(d[h] for h in hdr)
    # gw 20: all zero (missing); gw 21: one zero, one real (populated)
    extra = [row(20, "0.0", 612), row(20, "0.0", 541), row(21, "0.0", 612), row(21, "3.1", 541)]
    p = tmp_path / "merged.csv"
    p.write_text("\n".join(lines + extra) + "\n")
    history.load(tmp_db, "2025-26", p, FIX / "vaastav_fixtures.csv", FIX / "vaastav_teams.csv")
    q = "SELECT ep_pre FROM player_gw WHERE gw = ? AND player_id = ?"
    assert tmp_db.execute(q, (20, 612)).fetchone()[0] is None
    assert tmp_db.execute(q, (20, 541)).fetchone()[0] is None
    assert tmp_db.execute(q, (21, 612)).fetchone()[0] == 0.0
    assert tmp_db.execute(q, (21, 541)).fetchone()[0] == 3.1
