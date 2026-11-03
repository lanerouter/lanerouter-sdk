from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable

__version__ = "0.1.0"
__all__ = [
    "LaneRouter",
    "LaneRouterError",
    "RedLightError",
    "road_of",
    "classify",
    "verify_signature",
    "OUTCOMES",
    "DETOUR_KINDS",
]

DEFAULT_ENDPOINT = "https://lanerouter.com"
OUTCOMES = ("clear", "slow", "rate_limited", "wall", "changed", "broken")
DETOUR_KINDS = ("official_api", "alternate_endpoint", "wait_and_retry", "hand_to_human", "different_provider")

_OPAQUE = [
    re.compile(r"^\d+$"),
    re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I),
    re.compile(r"^[0-9a-f]{12,}$", re.I),
    re.compile(r"@"),
    re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9_-]{10,}$"),
]
_PREFIX = re.compile(r"^(v\d+(\.\d+)?|api|apis|rest|graphql|wp-json)$", re.I)
_CHALLENGE = re.compile(
    r"just a moment\.\.\.|cf-chl|challenge-platform|px-captcha|_incapsula_|request unsuccessful|are you a robot"
    r"|unusual traffic from your|perimeterx|datadome|pardon our interruption|automated access|unauthorized (ai )?agent"
    r"|enable javascript and cookies to continue|access to this page has been denied|g-recaptcha|h-captcha|hcaptcha\.com",
    re.I,
)
_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

log = logging.getLogger("lanerouter")


class LaneRouterError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RedLightError(Exception):
    def __init__(self, road: str, result: dict):
        super().__init__(f"LaneRouter: {road} is {result.get('condition')}. {result.get('advice') or ''}".strip())
        self.road = road
        self.condition = result.get("condition")
        self.detours = result.get("detours") or []
        self.advice = result.get("advice") or ""
        self.result = result


def _private_host(host: str) -> bool:
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return True
    if _IPV4.match(host):
        return True
    return ":" in host or "." not in host


def road_of(target: Any) -> dict | None:
    text = str(target or "").strip()
    if not text:
        return None
    if not re.match(r"^[a-z]+://", text, re.I):
        text = "https://" + text
    try:
        url = urllib.parse.urlsplit(text)
        host = (url.hostname or "").lower()
    except ValueError:
        return None
    if url.scheme not in ("http", "https"):
        return None
    host = re.sub(r"^www\.", "", host).rstrip(".")
    if not host or _private_host(host):
        return None
    segments: list[str] = []
    for raw in [s for s in url.path.split("/") if s]:
        seg = urllib.parse.unquote(raw)
        if any(r.search(seg) for r in _OPAQUE):
            break
        segments.append(seg.lower()[:48])
        if not _PREFIX.match(seg) or len(segments) >= 4:
            break
    path = "/" + "/".join(segments)
    return {"host": host, "path": path, "name": host + ("/" + "/".join(segments) if segments else "")}


def classify(status: int, latency_ms: float = 0, body: str = "", slow_ms: float = 5000) -> str:
    if body and _CHALLENGE.search(body):
        return "wall"
    if status == 429:
        return "rate_limited"
    if status in (401, 403):
        return "wall"
    if status >= 500:
        return "broken"
    if status in (404, 410):
        return "changed"
    return "slow" if latency_ms > slow_ms else "clear"


def verify_signature(body: str | bytes, header: str | None, secret: str, tolerance: int = 300, now: float | None = None) -> bool:
    if not header or not secret:
        return False
    parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
    try:
        t = int(parts.get("t", ""))
    except ValueError:
        return False
    v1 = parts.get("v1")
    if not v1 or abs((now if now is not None else time.time()) - t) > tolerance:
        return False
    raw = body if isinstance(body, bytes) else body.encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), f"{t}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def _urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


class LaneRouter:
    def __init__(
        self,
        key: str | None = None,
        endpoint: str | None = None,
        framework: str = "lanerouter-py",
        check: str = "warn",
        on_condition: Callable[[dict], Any] | None = None,
        slow_ms: float = 5000,
        timeout: float = 1.5,
        check_ttl: float = 60,
        report_every: float = 60,
        flush_interval: float = 5,
        ignore: Iterable[str] = (),
        debug: bool = False,
        transport: Callable[..., tuple[int, bytes]] | None = None,
    ):
        if check not in ("warn", "block", "off"):
            raise ValueError("check must be 'warn', 'block' or 'off'")
        self.key = key if key is not None else os.environ.get("LANEROUTER_KEY")
        self.endpoint = (endpoint or os.environ.get("LANEROUTER_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
        self.framework = str(framework)[:40]
        self.mode = check
        self.on_condition = on_condition
        self.slow_ms = slow_ms
        self.timeout = timeout
        self.check_ttl = check_ttl
        self.report_every = report_every
        self.flush_interval = flush_interval
        self.ignore = {re.sub(r"^www\.", "", h.lower()) for h in ignore}
        self.debug = debug
        self._transport = transport or _urllib_transport
        self._endpoint_host = re.sub(r"^www\.", "", urllib.parse.urlsplit(self.endpoint).hostname or "")
        self._checks: dict[str, tuple[float, dict | None]] = {}
        self._sent: dict[str, float] = {}
        self._warned: dict[str, float] = {}
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._patches: list[tuple[Any, str, Any]] = []

    def _log(self, *args: Any) -> None:
        if self.debug:
            log.debug(" ".join(str(a) for a in args))

    def _headers(self) -> dict:
        h = {"content-type": "application/json", "user-agent": f"lanerouter-py/{__version__}"}
        if self.key:
            h["authorization"] = f"Bearer {self.key}"
        return h

    def _call(self, method: str, path: str, body: dict | None = None) -> dict | None:
        try:
            status, raw = self._transport(method, self.endpoint + path, self._headers(), json.dumps(body).encode() if body is not None else None, self.timeout)
            if status >= 400:
                self._log("api", path, status)
                return None
            return json.loads(raw or b"{}")
        except Exception as err:
            self._log("api failed", path, err)
            return None

    def _manage(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
        if auth and not self.key:
            raise LaneRouterError("A LaneRouter key is required.", 401)
        status, raw = self._transport(method, self.endpoint + path, self._headers(), json.dumps(body).encode() if body is not None else None, max(self.timeout, 10))
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if status >= 400:
            raise LaneRouterError(data.get("error") or f"LaneRouter returned {status}", status)
        return data

    def _skip(self, road: dict | None) -> bool:
        return not road or road["host"] == self._endpoint_host or road["host"] in self.ignore

    def check(self, target: Any, action: str | None = None) -> dict | None:
        road = road_of(target)
        if not road:
            return None
        k = f"{road['name']}|{action or ''}"
        cached = self._checks.get(k)
        if cached and time.monotonic() - cached[0] < self.check_ttl:
            return cached[1]
        q = {"target": road["name"]}
        if action:
            q["action"] = action
        value = self._call("GET", "/api/v1/check?" + urllib.parse.urlencode(q))
        self._checks[k] = (time.monotonic(), value)
        return value

    def report(self, target: Any, outcome: str, action: str | None = None, http_status: int | None = None, latency_ms: float | None = None, detour: dict | None = None) -> bool:
        if not self.key:
            return False
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        if detour and detour.get("kind") not in DETOUR_KINDS:
            raise ValueError(f"detour kind must be one of: {', '.join(DETOUR_KINDS)}")
        road = road_of(target)
        if self._skip(road):
            return False
        k = f"{road['name']}|{action or ''}|{outcome}"
        now = time.monotonic()
        with self._lock:
            last = self._sent.get(k)
            if not detour and last is not None and now - last < self.report_every:
                return False
            self._sent[k] = now
            item: dict[str, Any] = {"target": road["name"], "outcome": outcome, "framework": self.framework}
            if action:
                item["action"] = action
            if isinstance(http_status, int):
                item["http_status"] = http_status
            if latency_ms is not None:
                item["latency_ms"] = round(latency_ms)
            if detour:
                d = {"kind": detour["kind"], "worked": bool(detour.get("worked"))}
                if detour.get("target"):
                    d["target"] = str(detour["target"])
                if detour.get("note"):
                    d["note"] = str(detour["note"])[:140]
                item["detour"] = d
            self._queue.append(item)
            full = len(self._queue) >= 25
            if not full and self._timer is None:
                self._timer = threading.Timer(self.flush_interval, self.flush)
                self._timer.daemon = True
                self._timer.start()
        if full:
            self.flush()
        return True

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            batches = [self._queue[i:i + 50] for i in range(0, len(self._queue), 50)]
            self._queue = []
        for batch in batches:
            self._call("POST", "/api/v1/reports", {"reports": batch})

    def before(self, url: Any, method: str = "GET") -> dict | None:
        road = road_of(url)
        if self._skip(road) or self.mode == "off":
            return None
        result = self.check(url, action=method.lower())
        if result and result.get("light") not in (None, "green", "off"):
            if self.on_condition:
                try:
                    self.on_condition({"road": road["name"], **result})
                except Exception:
                    pass
            elif self.mode == "warn":
                w = self._warned.get(road["name"])
                if w is None or time.monotonic() - w > self.check_ttl:
                    self._warned[road["name"]] = time.monotonic()
                    log.warning(f"[lanerouter] {road['name']}: {result.get('condition')}. {result.get('advice') or ''}".strip())
            if self.mode == "block" and result.get("light") == "red":
                raise RedLightError(road["name"], result)
        return result

    def after(self, url: Any, method: str, status: int, latency_ms: float, body: str = "") -> bool:
        return self.report(url, classify(status, latency_ms, body, self.slow_ms), action=method.lower(), http_status=status, latency_ms=latency_ms)

    def install(self) -> Callable[[], None]:
        if self._patches:
            return self.uninstall
        self._patch_requests()
        self._patch_httpx()
        return self.uninstall

    def uninstall(self) -> None:
        for owner, name, original in reversed(self._patches):
            setattr(owner, name, original)
        self._patches = []

    def _patch(self, owner: Any, name: str, wrapper: Any) -> None:
        self._patches.append((owner, name, getattr(owner, name)))
        setattr(owner, name, wrapper)

    def _patch_requests(self) -> None:
        try:
            import requests
        except ImportError:
            return
        lanes = self
        original = requests.Session.send

        def send(session, request, **kwargs):
            url, method = request.url, request.method or "GET"
            lanes.before(url, method)
            started = time.monotonic()
            response = original(session, request, **kwargs)
            latency = (time.monotonic() - started) * 1000
            body = ""
            if response.status_code in (401, 403, 503) and "html" in response.headers.get("content-type", "") and not kwargs.get("stream"):
                body = response.text[:65536]
            lanes.after(url, method, response.status_code, latency, body)
            return response

        self._patch(requests.Session, "send", send)

    def _patch_httpx(self) -> None:
        try:
            import httpx
        except ImportError:
            return
        lanes = self
        sync_send = httpx.Client.send
        async_send = httpx.AsyncClient.send

        def body_of(response, stream):
            if stream or response.status_code not in (401, 403, 503) or "html" not in response.headers.get("content-type", ""):
                return ""
            try:
                return response.text[:65536]
            except Exception:
                return ""

        def send(client, request, *args, **kwargs):
            url, method = str(request.url), request.method
            lanes.before(url, method)
            started = time.monotonic()
            response = sync_send(client, request, *args, **kwargs)
            lanes.after(url, method, response.status_code, (time.monotonic() - started) * 1000, body_of(response, kwargs.get("stream")))
            return response

        async def asend(client, request, *args, **kwargs):
            url, method = str(request.url), request.method
            await asyncio.to_thread(lanes.before, url, method)
            started = time.monotonic()
            response = await async_send(client, request, *args, **kwargs)
            lanes.after(url, method, response.status_code, (time.monotonic() - started) * 1000, body_of(response, kwargs.get("stream")))
            return response

        self._patch(httpx.Client, "send", send)
        self._patch(httpx.AsyncClient, "send", asend)

    def watch(self, target: Any, url: str, action: str | None = None) -> dict:
        body: dict[str, Any] = {"target": str(target), "url": url}
        if action:
            body["action"] = action
        return self._manage("POST", "/api/v1/watches", body)

    def unwatch(self, watch_id: int) -> None:
        self._manage("DELETE", f"/api/v1/watches/{int(watch_id)}")

    def watches(self) -> list[dict]:
        return self._manage("GET", "/api/v1/watches").get("watches", [])

    def history(self, road_id: int, days: int = 30) -> dict:
        return self._manage("GET", f"/api/v1/roads/{int(road_id)}/history?days={int(days)}", auth=False)

    def close(self) -> None:
        self.uninstall()
        self.flush()

    def __enter__(self) -> "LaneRouter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
