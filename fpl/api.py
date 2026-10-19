"""Polite client for the official FPL API."""
import time

import requests

BASE_URL = "https://fantasy.premierleague.com/api/"
USER_AGENT = "fpl-team-analyser/0.1 (personal project)"
MAX_RETRIES = 3
TIMEOUT = 20


class FplApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class FplClient:
    def __init__(self, session=None, min_interval=0.5, sleep=time.sleep, clock=time.monotonic):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_call = None

    def _wait_turn(self):
        if self._last_call is not None:
            remaining = self.min_interval - (self._clock() - self._last_call)
            if remaining > 0:
                self._sleep(remaining)
        self._last_call = self._clock()

    def get(self, path):
        url = BASE_URL + path
        for attempt in range(MAX_RETRIES + 1):
            self._wait_turn()
            try:
                resp = self.session.get(url, timeout=TIMEOUT)
            except requests.RequestException as exc:
                raise FplApiError(f"Network error calling {url}: {exc}", status=None) from exc
            status = resp.status_code
            if status == 200:
                return resp.json()
            retryable = status == 429 or status >= 500
            if not retryable or attempt == MAX_RETRIES:
                raise FplApiError(f"FPL API returned {status} for {url}", status=status)
            self._sleep(2 ** attempt)

    def bootstrap(self):
        return self.get("bootstrap-static/")

    def fixtures(self):
        return self.get("fixtures/")

    def event_live(self, gw):
        return self.get(f"event/{gw}/live/")

    def entry(self, team_id):
        return self.get(f"entry/{team_id}/")

    def entry_history(self, team_id):
        return self.get(f"entry/{team_id}/history/")

    def entry_picks(self, team_id, gw):
        return self.get(f"entry/{team_id}/event/{gw}/picks/")

    def entry_transfers(self, team_id):
        return self.get(f"entry/{team_id}/transfers/")

    def element_summary(self, player_id):
        return self.get(f"element-summary/{player_id}/")
