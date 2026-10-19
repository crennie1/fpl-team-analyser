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
