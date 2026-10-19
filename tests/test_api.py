import pytest
import requests

from fpl.api import FplApiError, FplClient


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(responses):
    session = FakeSession(responses)
    sleeps = []
    client = FplClient(session=session, sleep=sleeps.append)
    return client, session, sleeps


def test_get_returns_json():
    client, session, _ = make([FakeResponse(200, {"a": 1})])
    assert client.get("bootstrap-static/") == {"a": 1}
    assert session.calls == ["https://fantasy.premierleague.com/api/bootstrap-static/"]


def test_get_retries_then_succeeds():
    client, session, sleeps = make(
        [FakeResponse(503), FakeResponse(503), FakeResponse(200, {"ok": True})]
    )
    assert client.get("x/") == {"ok": True}
    assert len(session.calls) == 3
    assert 1 in sleeps and 2 in sleeps


def test_get_404_raises():
    client, session, _ = make([FakeResponse(404)])
    with pytest.raises(FplApiError) as exc:
        client.get("x/")
    assert exc.value.status == 404
    assert len(session.calls) == 1


def test_get_gives_up_after_3_retries():
    client, session, sleeps = make([FakeResponse(503)] * 4)
    with pytest.raises(FplApiError) as exc:
        client.get("x/")
    assert exc.value.status == 503
    assert len(session.calls) == 4
    assert [s for s in sleeps if s >= 1] == [1, 2, 4]


def test_network_error_raises_with_no_status():
    client, _, _ = make([requests.ConnectionError("boom")])
    with pytest.raises(FplApiError) as exc:
        client.get("x/")
    assert exc.value.status is None


def test_user_agent_sent():
    session = FakeSession([])
    FplClient(session=session, sleep=lambda s: None)
    assert "fpl-team-analyser" in session.headers["User-Agent"]


def test_convenience_paths():
    client, session, _ = make([FakeResponse(200, {})] * 8)
    client.bootstrap()
    client.fixtures()
    client.event_live(3)
    client.entry(7)
    client.entry_history(7)
    client.entry_picks(7, 3)
    client.entry_transfers(7)
    client.element_summary(9)
    base = "https://fantasy.premierleague.com/api/"
    assert [u[len(base):] for u in session.calls] == [
        "bootstrap-static/", "fixtures/", "event/3/live/", "entry/7/",
        "entry/7/history/", "entry/7/event/3/picks/", "entry/7/transfers/",
        "element-summary/9/",
    ]


def test_non_json_200_raises_api_error():
    client, session, _ = make([FakeResponse(200, ValueError("Expecting value"))])
    with pytest.raises(FplApiError) as exc:
        client.get("x/")
    assert exc.value.status == 200
    assert len(session.calls) == 1
