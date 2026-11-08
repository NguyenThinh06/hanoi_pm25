"""Bounded, process-local JSON cache; never retain request or database objects."""

import math
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import monotonic

from fastapi.responses import Response

from .schemas import Schema

CacheKey = tuple[str, str]


class ResponseCache:
    """LRU eviction plus absolute TTL, with immutable payloads and a byte budget."""

    def __init__(
        self,
        ttl: float = 300,
        max_entries: int = 129,
        max_bytes: int = 32 * 1024 * 1024,
        clock: Callable[[], float] = monotonic,
    ):
        if not math.isfinite(ttl) or ttl < 0 or max_entries < 1 or max_bytes < 1:
            raise ValueError("Invalid cache limits")
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.clock = clock
        self._entries: OrderedDict[CacheKey, tuple[float, bytes, int]] = OrderedDict()
        self._bytes = 0
        self._generation = 0
        self._lock = Lock()

    def begin(self) -> "CacheSession":
        with self._lock:
            return CacheSession(self, self._generation, self.clock())

    def get(self, key: CacheKey) -> bytes | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, payload, _ = entry
            if self.clock() >= expires:
                self._remove(key)
                return None
            self._entries.move_to_end(key)
            return payload

    def _remove(self, key: CacheKey) -> None:
        self._bytes -= self._entries.pop(key)[2]

    def put(self, key: CacheKey, payload: bytes, generation: int, started: float) -> None:
        # Count encoded keys too; Python object overhead is separately bounded by max_entries.
        size = len(payload) + sum(len(part.encode("utf-8")) for part in key)
        with self._lock:
            now = self.clock()
            if generation != self._generation or now >= started + self.ttl or size > self.max_bytes:
                return
            for old_key, (expires, _, _) in list(self._entries.items()):
                if now >= expires:
                    self._remove(old_key)
            if key in self._entries:
                # A concurrent, newer load must not be overwritten by a slow older request.
                if self._entries[key][0] > started + self.ttl:
                    return
                self._remove(key)
            while self._entries and (len(self._entries) >= self.max_entries or self._bytes + size > self.max_bytes):
                self._remove(next(iter(self._entries)))
            self._entries[key] = (started + self.ttl, payload, size)
            self._bytes += size

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            # Loads already in flight cannot repopulate a cleared cache.
            self._generation += 1


class CacheSession:
    """Stage validated JSON, publish only after successful request/DB teardown."""

    def __init__(self, cache: ResponseCache, generation: int, started: float):
        self.cache = cache
        self.generation = generation
        self.started = started
        self.pending: tuple[CacheKey, bytes] | None = None

    def get(self, key: CacheKey) -> Response | None:
        payload = self.cache.get(key)
        return Response(payload, media_type="application/json") if payload is not None else None

    def stage(self, key: CacheKey, validated: Schema) -> Response:
        payload = validated.model_dump_json().encode("utf-8")
        self.pending = (key, payload)
        return Response(payload, media_type="application/json")

    def publish(self) -> None:
        if self.pending is not None:
            key, payload = self.pending
            self.cache.put(key, payload, self.generation, self.started)
            self.pending = None
