"""Robust cached HTTP.

Every external fetch in this project goes through here, for three reasons.

1. **Nothing raises on a network problem.** `get_json` returns ``None``. Callers
   degrade and say so; they never crash a forecast run because a CDN hiccupped.
2. **Disk cache with TTL.** Archive requests for a past date are cached for a month
   because the answer cannot change. Forecast requests are cached for an hour because
   the upstream model only runs four times a day. This makes re-runs during development
   free, and makes the whole pipeline reproducible offline once warmed.
3. **Retry with backoff and jitter.** Open-Meteo and OpenAQ both rate-limit. A bare
   failure on request 400 of 500 would otherwise lose the whole run.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import config as C

_MEM: dict[str, tuple[float, Any]] = {}


def _key(url: str, headers: dict | None) -> str:
    raw = url + "|" + json.dumps(sorted((headers or {}).items()))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cache_path(key: str):
    return C.CACHE / f"{key}.json"


def cache_get(key: str, ttl: float) -> Any | None:
    hit = _MEM.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    path = _cache_path(key)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime >= ttl:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A truncated cache file is worth nothing and worth less than a crash.
        try:
            path.unlink()
        except OSError:
            pass
        return None
    _MEM[key] = (path.stat().st_mtime, payload)
    return payload


def cache_put(key: str, payload: Any) -> None:
    _MEM[key] = (time.time(), payload)
    tmp = _cache_path(key).with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(_cache_path(key))  # atomic; a killed run cannot leave a half file
    except OSError:
        pass


def get_json(
    url: str,
    *,
    headers: dict | None = None,
    ttl: float = C.CACHE_TTL_FORECAST,
    retries: int = C.HTTP_RETRIES,
    timeout: float = C.HTTP_TIMEOUT,
) -> Any | None:
    """GET a JSON document. Returns None on any failure, never raises."""
    key = _key(url, headers)
    cached = cache_get(key, ttl)
    if cached is not None:
        return cached

    hdrs = {"User-Agent": C.USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})

    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            cache_put(key, payload)
            return payload
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            # 4xx other than 429 will not become true by asking again.
            if exc.code not in (429, 500, 502, 503, 504):
                break
            if exc.code in (429, 502, 503, 504):
                # Rate limits and gateway errors need a different scale of patience from
                # a flaky connection. Open-Meteo's archive limit is per-minute, so the
                # ordinary ~2 s backoff simply re-triggers it and burns the retry budget;
                # the request then "fails" and a caller silently proceeds with a hole in
                # its data. A single 502 killed an entire hindcast's meteorology this
                # way. Honour Retry-After when given, otherwise wait out the window.
                wait = float(exc.headers.get("Retry-After") or 0) or (15.0 * (attempt + 1))
                print(f"[net] HTTP {exc.code}, waiting {wait:.0f}s before retry")
                time.sleep(min(wait, 70.0))
                continue
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < retries - 1:
            time.sleep(C.HTTP_BACKOFF ** attempt + random.uniform(0, 0.4))

    # Serve a stale hit rather than nothing: an hour-old boundary layer height is far
    # better than a hole in the feature matrix.
    stale = cache_get(key, ttl=C.CACHE_TTL_ARCHIVE)
    if stale is not None:
        return stale
    print(f"[net] give up {url.split('?')[0]} -> {last}")
    return None


def get_text(url: str, *, headers: dict | None = None, ttl: float = C.CACHE_TTL_FORECAST,
             retries: int = C.HTTP_RETRIES, timeout: float = C.HTTP_TIMEOUT) -> str | None:
    """GET a text document (FIRMS serves CSV). Returns None on any failure."""
    key = "txt" + _key(url, headers)
    cached = cache_get(key, ttl)
    if cached is not None:
        return cached
    hdrs = {"User-Agent": C.USER_AGENT}
    hdrs.update(headers or {})
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            cache_put(key, body)
            return body
        except Exception:
            if attempt < retries - 1:
                time.sleep(C.HTTP_BACKOFF ** attempt + random.uniform(0, 0.4))
    return cache_get(key, ttl=C.CACHE_TTL_ARCHIVE)


def build_url(base: str, params: dict) -> str:
    """Stable query ordering, so the same logical request hits the same cache entry."""
    clean = {k: v for k, v in params.items() if v is not None}
    return base + "?" + urllib.parse.urlencode(sorted(clean.items()), doseq=True)
