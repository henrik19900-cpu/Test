"""Norsk Tipping's Oddsen, read through the JSON calls its own web page makes.

Norsk Tipping has no public odds API. These calls were found by watching the Oddsen page in a
browser (DevTools, Network), and are unofficial: they can change without notice. When the
answers do not look as expected, the adapter raises SourceError saying what was missing; it never
returns an empty list quietly.

How the page gets its odds:

1. POST {base_url}/content/get with a boNavigationList id gives the menu: Fotball, its countries,
   their leagues. A league with matches has a market group of type MATCHESCOUPON.
2. The match odds are not in any plain response. The page opens a SockJS websocket at
   {websocket_url}, which answers with a subscriber id (LISTENING_STARTED).
3. POST {base_url}/content/subscribe with that id and an eventGroup (the market group) makes the
   server push the group's matches, with their main market (HUB = 1X2), over the websocket.

Prices are fractions (currentpriceup / currentpricedown); the decimal odds are 1 + up/down,
rounded to two decimals as the page shows them.

To keep the load on Norsk Tipping low: one round of calls at most every min_interval_minutes
(the last answer is cached on disk and reused until then), the league menu is cached for
navigation_cache_hours, and only the countries in the config are read.
"""

from __future__ import annotations

import json
import logging
import random
import string
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect as ws_connect

from ..config import NorskTippingConfig
from . import RawEvent, SourceError

logger = logging.getLogger(__name__)

CHANNEL = "1355"  # Oddsen's id in the navigation ids
FOOTBALL = "42978.1"  # Oddsen > Fotball
COUPON = "MATCHESCOUPON"
OUTCOME_BY_HAD = {"H": "home", "D": "draw", "A": "away"}
WORKERS = 4  # parallel requests, about what the page itself does

# A websocket as used here: send a text frame, receive one (with a timeout in seconds), close.
Stream = AbstractContextManager[Any]
StreamFactory = Callable[[str, dict[str, str]], Stream]


class NorskTipping:
    name = "norsk_tipping"

    def __init__(
        self,
        cfg: NorskTippingConfig,
        user_agent: str,
        cache_dir: Path | None = None,
        client: httpx.Client | None = None,
        stream_factory: StreamFactory | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.client = client or httpx.Client(timeout=cfg.timeout_seconds)
        self.headers = {
            "user-agent": user_agent,
            "accept": "application/json",
            "content-type": "application/json",
            "poseidon": "oddsen",  # the page sends it on every call; the server routes on it
        }
        self.stream_factory = stream_factory or _websocket
        self.clock = clock
        self.fetched_at: datetime | None = None  # when the odds of the last fetch() were read from the site

    def fetch(self, days_ahead: int) -> list[RawEvent]:
        now = self.clock()
        snapshot = self._cached("norsk_tipping.json", timedelta(minutes=self.cfg.min_interval_minutes), now)
        if snapshot is None:
            groups = self._coupons(now)
            snapshot = {"fetched_at_utc": now.isoformat(), "event_groups": self._event_groups(groups)}
            self._store("norsk_tipping.json", snapshot)
        else:
            logger.info("Norsk Tipping: using the cached answer from %s", snapshot["fetched_at_utc"])
        self.fetched_at = datetime.fromisoformat(snapshot["fetched_at_utc"])
        return parse_event_groups(snapshot["event_groups"], now, days_ahead)

    # The menu: which market groups (one per league) to subscribe to.

    def _coupons(self, now: datetime) -> list[dict[str, str]]:
        ttl = timedelta(hours=self.cfg.navigation_cache_hours)
        cached = self._cached("norsk_tipping_navigation.json", ttl, now) if ttl else None
        if cached is not None:
            return cached["coupons"]
        football = self._content("get", "boNavigationList", f"{CHANNEL}/{FOOTBALL}")
        countries = _children(football, f"boNavigationList {FOOTBALL}")
        wanted = {c.casefold() for c in self.cfg.countries}
        countries = [c for c in countries if not wanted or c.get("name", "").casefold() in wanted]
        if wanted and not countries:
            raise SourceError(
                f"Norsk Tipping: fant ingen av landene {', '.join(self.cfg.countries)} i fotballmenyen",
                retryable=False,
            )
        coupons = self._walk(countries, depth=0)
        if not coupons:
            raise SourceError(
                "Norsk Tipping: fant ingen kampkuponger i menyen (har formatet endret seg?)", retryable=False
            )
        self._store("norsk_tipping_navigation.json", {"fetched_at_utc": now.isoformat(), "coupons": coupons})
        return coupons

    def _walk(self, nodes: list[dict[str, Any]], depth: int) -> list[dict[str, str]]:
        """Open every node with matches; collect the match coupons of those that have one."""
        nodes = [n for n in nodes if _count(n, "numevents") > 0]
        if not nodes or depth > 3:
            return []
        with ThreadPoolExecutor(WORKERS) as pool:
            opened = list(
                pool.map(
                    lambda n: self._content("get", "boNavigationList", f"{CHANNEL}/{n['idfwbonavigation']}"),
                    nodes,
                )
            )
        coupons, deeper = [], []
        for node in opened:
            groups = [g for g in node.get("marketgroups", []) if g.get("idfwmarketgrouptype") == COUPON]
            coupons += [{"id": g["idfwmarketgroup"], "name": node.get("name", "")} for g in groups]
            if not groups:
                deeper += node.get("bonavigationnodes", [])
        return coupons + self._walk(deeper, depth + 1)

    # The matches: subscribe to every coupon and collect what the websocket pushes.

    def _event_groups(self, coupons: list[dict[str, str]]) -> dict[str, Any]:
        wanted = {c["id"] for c in coupons}
        received: dict[str, Any] = {}
        deadline = time.monotonic() + self.cfg.timeout_seconds
        url = _sockjs_url(self.cfg.websocket_url)
        try:
            with self.stream_factory(url, {"user-agent": self.headers["user-agent"]}) as ws:
                subscriber = self._listen(ws, deadline)
                with ThreadPoolExecutor(WORKERS) as pool:
                    list(pool.map(lambda gid: self._subscribe(subscriber, gid), sorted(wanted)))
                while wanted - received.keys():
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    try:
                        frame = ws.recv(timeout=left)
                    except TimeoutError:
                        break
                    for item in _messages(frame):
                        content = item.get("contentId") or {}
                        if content.get("type") == "eventGroup" and item.get("changeType") == "refreshed":
                            received[content.get("id")] = item.get("change") or {}
        except (OSError, WebSocketException) as e:
            raise SourceError(f"Norsk Tipping: websocketen feilet ({type(e).__name__}: {e})") from e
        if not received:
            raise SourceError("Norsk Tipping: fikk ingen kamper over websocketen innen tidsfristen")
        missing = wanted - received.keys()
        if missing:
            logger.warning("Norsk Tipping: no answer for %d of %d coupons", len(missing), len(wanted))
        return received

    def _listen(self, ws: Any, deadline: float) -> str:
        """The SockJS handshake: wait for 'o', ask to listen, and return the subscriber id."""
        hello = {"subscriberId": None, "versionList": [], "clientContext": {"language": "NO"}}
        sent = False
        while (left := deadline - time.monotonic()) > 0:
            frame = ws.recv(timeout=left)
            if frame == "o" and not sent:
                ws.send(json.dumps([json.dumps(hello)]))
                sent = True
                continue
            for item in _messages(frame, raw=True):
                if item.get("notificationType") == "LISTENING_STARTED" and item.get("data"):
                    return str(item["data"])
        raise SourceError("Norsk Tipping: websocketen ga ingen abonnent-id (LISTENING_STARTED)")

    def _subscribe(self, subscriber: str, group_id: str) -> None:
        self._content("subscribe", "eventGroup", group_id, subscriberId=subscriber)

    # Plumbing

    def _content(self, action: str, kind: str, content_id: str, **extra: Any) -> Any:
        body = {**extra, "contentId": {"type": kind, "id": content_id}, "clientContext": {"language": "NO"}}
        try:
            response = self.client.post(
                f"{self.cfg.base_url}/content/{action}", json=body, headers=self.headers
            )
        except httpx.HTTPError as e:
            raise SourceError(f"Norsk Tipping svarte ikke på content/{action} ({type(e).__name__})") from e
        if response.status_code in (401, 403):
            raise SourceError(
                f"Norsk Tipping krever nå innlogging eller avviste kallet (HTTP {response.status_code})",
                retryable=False,
            )
        if response.status_code >= 400:
            raise SourceError(
                f"Norsk Tipping svarte {response.status_code} på content/{action} {kind} {content_id}"
            )
        try:
            payload = response.json()
        except ValueError as e:
            raise SourceError(f"Norsk Tipping sendte ikke JSON på content/{action}") from e
        if action == "get":
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                raise SourceError(
                    f"Norsk Tipping: uventet svar på {kind} {content_id} (mangler data)", retryable=False
                )
            return payload["data"]
        return payload

    def _cached(self, name: str, ttl: timedelta, now: datetime) -> dict[str, Any] | None:
        if not self.cache_dir or not (self.cache_dir / name).exists():
            return None
        try:
            payload = json.loads((self.cache_dir / name).read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(payload["fetched_at_utc"])
        except (OSError, ValueError, KeyError):
            return None
        return payload if timedelta(0) <= now - fetched < ttl else None

    def _store(self, name: str, payload: dict[str, Any]) -> None:
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def parse_event_groups(groups: dict[str, Any], now: datetime, days_ahead: int) -> list[RawEvent]:
    """The 1X2 odds of every match that kicks off from now and days_ahead days on, once per match."""
    end = now + timedelta(days=days_ahead)
    events: dict[str, RawEvent] = {}
    seen = broken = 0
    for group in groups.values():
        for event in group.get("events") or []:
            seen += 1
            try:
                raw = _event(event)
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
                broken += 1
                logger.debug("Norsk Tipping: skipping event %s: %s", event.get("idfoevent"), e)
                continue
            if raw is not None and now < raw.kickoff_utc <= end:
                events.setdefault(raw.source_event_id, raw)
    if seen and broken == seen:
        raise SourceError(
            f"Norsk Tipping: ingen av {seen} kamper hadde forventet format (har formatet endret seg?)",
            retryable=False,
        )
    return sorted(events.values(), key=lambda e: (e.kickoff_utc, e.source_event_id))


def _event(event: dict[str, Any]) -> RawEvent | None:
    """One match, or None when it has no open 1X2 market with all three prices."""
    kickoff = datetime.fromisoformat(event["tsstart"]).astimezone(UTC)
    for market in event.get("markets") or []:
        if market.get("idfomarketlinetype") != "MONEY" or market.get("istradable") is False:
            continue
        odds = {}
        for selection in market.get("selections") or []:
            outcome = OUTCOME_BY_HAD.get(selection.get("hadvalue"))
            if outcome and not selection.get("idfoselectionsuspensiontype"):
                odds[outcome] = decimal_odds(selection["currentpriceup"], selection["currentpricedown"])
        if len(odds) == 3:
            return RawEvent(
                source=NorskTipping.name,
                source_event_id=str(event["idfoevent"]),
                home=event["participantname_home"],
                away=event["participantname_away"],
                league=event.get("tournamentname") or market.get("tournamentname") or "",
                kickoff_utc=kickoff,
                odds=odds,
            )
    return None


def decimal_odds(up: str | int, down: str | int) -> float:
    """Fractional price to decimal odds as the page shows them: 31/10 is 4.10."""
    return round(1 + int(up) / int(down), 2)


def _children(node: dict[str, Any], what: str) -> list[dict[str, Any]]:
    children = node.get("bonavigationnodes")
    if not isinstance(children, list):
        raise SourceError(
            f"Norsk Tipping: uventet svar på {what} (mangler bonavigationnodes)", retryable=False
        )
    return children


def _count(node: dict[str, Any], key: str) -> int:
    try:
        return int(node.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _messages(frame: str | bytes, raw: bool = False) -> Iterable[dict[str, Any]]:
    """The notifications in one SockJS frame ('a' + a JSON list of JSON strings); nothing for 'o', 'h', 'c'.

    raw=True yields each notification whole; otherwise the items of its data list.
    """
    if isinstance(frame, bytes):
        frame = frame.decode("utf-8")
    if not frame.startswith("a"):
        return
    for text in json.loads(frame[1:]):
        message = json.loads(text)
        if raw:
            yield message
        elif isinstance(message.get("data"), list):
            yield from message["data"]


def _sockjs_url(base: str) -> str:
    server = random.randrange(1000)
    session = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{base.rstrip('/')}/{server:03d}/{session}/websocket"


def _websocket(url: str, headers: dict[str, str]) -> Stream:
    return ws_connect(
        url,
        user_agent_header=headers.get("user-agent"),
        origin="https://www.norsk-tipping.no",
        open_timeout=15,
        max_size=2**24,  # a big league's coupon is a few hundred kB
    )
