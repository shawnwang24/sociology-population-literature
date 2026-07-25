from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session(user_agent: str, retries: int = 4) -> requests.Session:
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
