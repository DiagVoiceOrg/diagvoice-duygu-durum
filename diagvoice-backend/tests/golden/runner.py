"""Bir golden vakasını HTTP isteği olarak gönderir."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from tests.golden.cases import SAMPLES_DIR, Case


@dataclass
class Result:
    status: int
    body: Any          # JSON ise dict/list, değilse metin
    is_json: bool
    seconds: float


def send_case(
    client: httpx.Client,
    base_url: str,
    case: Case,
    *,
    api_key: Optional[str] = None,
) -> Result:
    url = base_url.rstrip("/") + case.path
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    kwargs: dict[str, Any] = {"headers": headers, "params": case.query or None}
    fh = None
    try:
        if case.audio:
            p = SAMPLES_DIR / case.audio
            if not p.is_file():
                raise FileNotFoundError(f"Örnek ses yok: {p}")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            fh = p.open("rb")
            kwargs["files"] = {case.file_field: (p.name, fh, ctype)}
            kwargs["data"] = case.form or None
        elif case.json is not None:
            kwargs["json"] = case.json
        elif case.form:
            kwargs["data"] = case.form

        r = client.request(case.method, url, **kwargs)
    finally:
        if fh is not None:
            fh.close()

    try:
        body: Any = r.json()
        is_json = True
    except ValueError:
        body, is_json = r.text, False
    return Result(status=r.status_code, body=body, is_json=is_json, seconds=r.elapsed.total_seconds())


def make_client(timeout_sec: float = 600.0) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=10.0))
