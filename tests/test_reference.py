import json

from fpl import reference
from fpl.api import FplApiError
from tests.conftest import FIXTURES


class PicksClient:
    def __init__(self, missing=lambda eid: False, total=50):
        self.missing, self.total = missing, total
        self.picks = json.loads((FIXTURES / "entry_picks_ok.json").read_text())

    def bootstrap(self):
        return {"total_players": self.total}

    def entry(self, team_id):
        if self.missing(team_id):
            raise FplApiError("nope", status=404)
        return {"id": team_id}

    def entry_picks(self, team_id, gw):
        return self.picks


def _count(conn, sql, *a):
    return conn.execute(sql, a).fetchone()[0]


def test_sample_skips_404_and_reaches_n(tmp_db):
    client = PicksClient(missing=lambda eid: eid % 2 == 0)
    assert reference.sample(tmp_db, client, "2026-27", 7, n=10, seed=1) == 10
    assert _count(tmp_db, "SELECT COUNT(*) FROM reference_squad") == 10
    assert _count(tmp_db, "SELECT COUNT(*) FROM squad_pick") == 150
    row = tmp_db.execute(
        "SELECT * FROM squad_pick WHERE slot = 3 LIMIT 1").fetchone()
    assert row["is_captain"] == 1 and row["is_starter"] == 1
    assert _count(tmp_db, "SELECT SUM(is_starter) FROM squad_pick") == 110
    assert _count(tmp_db, "SELECT COUNT(*) FROM reference_squad WHERE squad_id = 'ref:' || entry_id") == 10


def test_sample_stops_after_3n_attempts(tmp_db):
    client = PicksClient(missing=lambda eid: True, total=10_000)
    calls = []
    orig = client.entry
    client.entry = lambda eid: (calls.append(eid), orig(eid))[1]
    assert reference.sample(tmp_db, client, "2026-27", 7, n=5, seed=1) == 0
    assert len(calls) == 15
    assert _count(tmp_db, "SELECT COUNT(*) FROM reference_squad") == 0


def test_sample_replaces_previous_and_keeps_user_squad(tmp_db):
    tmp_db.execute("INSERT INTO squad_pick VALUES ('user', 1, 1, 1, 0)")
    reference.sample(tmp_db, PicksClient(), "2026-27", 6, n=5, seed=1)
    reference.sample(tmp_db, PicksClient(), "2026-27", 7, n=4, seed=2)
    assert _count(tmp_db, "SELECT COUNT(*) FROM reference_squad") == 4
    assert _count(tmp_db, "SELECT COUNT(DISTINCT gw) FROM reference_squad") == 1
    assert _count(tmp_db, "SELECT COUNT(*) FROM squad_pick WHERE squad_id LIKE 'ref:%'") == 60
    assert _count(tmp_db, "SELECT COUNT(*) FROM squad_pick WHERE squad_id = 'user'") == 1


class FlakyClient(PicksClient):
    def __init__(self, bad_ids, **kw):
        super().__init__(**kw)
        self.bad = bad_ids

    def entry(self, team_id):
        if team_id in self.bad:
            raise FplApiError("boom", status=500)
        return super().entry(team_id)


def test_sample_skips_server_errors_then_caps(tmp_db):
    import pytest
    few = FlakyClient({1, 2, 3}, total=50)
    assert reference.sample(tmp_db, few, "2026-27", 7, n=10, seed=1) == 10
    down = FlakyClient(set(range(1, 1001)), total=1000)
    with pytest.raises(FplApiError):
        reference.sample(tmp_db, down, "2026-27", 7, n=10, seed=1)


def test_sample_ends_when_pool_smaller_than_attempts(tmp_db):
    client = PicksClient(missing=lambda eid: True, total=5)
    assert reference.sample(tmp_db, client, "2026-27", 7, n=10, seed=1) == 0
