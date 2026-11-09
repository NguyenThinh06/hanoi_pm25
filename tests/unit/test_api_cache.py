"""Deterministic RAM cache tests: no DB, sleeps or external services."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from src.api.cache import ResponseCache
from src.api.config import DEFAULT_CORS_ORIGINS, Settings
from src.api.schemas import GridsResponse


def store(cache, key, payload=b"{}"):
    session = cache.begin()
    cache.put(key, payload, session.generation, session.started)


def test_absolute_ttl_is_not_extended_by_hits():
    now = Mock(return_value=10)
    cache = ResponseCache(ttl=5, clock=now)
    key = ("dates", "model")
    store(cache, key)
    now.return_value = 14
    assert cache.get(key) == b"{}"
    now.return_value = 15
    assert cache.get(key) is None


def test_entry_limit_evicts_least_recently_used():
    cache = ResponseCache(max_entries=2)
    a, b, c = [("dates", name) for name in "abc"]
    store(cache, a)
    store(cache, b)
    assert cache.get(a) == b"{}"
    store(cache, c)
    assert cache.get(b) is None
    assert cache.get(a) == cache.get(c) == b"{}"


def test_byte_limit_and_oversize_bypass():
    cache = ResponseCache(max_bytes=10)
    store(cache, ("", "a"), b"123456")
    store(cache, ("", "b"), b"123456")
    assert cache.get(("", "a")) is None
    assert cache.get(("", "b")) == b"123456"
    store(cache, ("", "c"), b"x" * 11)
    assert cache.get(("", "c")) is None
    assert cache.get(("", "b")) == b"123456"


def test_clear_blocks_inflight_publication():
    cache = ResponseCache()
    pending = cache.begin()
    pending.stage(("grids", ""), GridsResponse(features=[]))
    cache.clear()
    pending.publish()
    assert cache.get(("grids", "")) is None
    fresh = cache.begin()
    fresh.stage(("grids", ""), GridsResponse(features=[]))
    fresh.publish()
    assert cache.get(("grids", "")) is not None


def test_slow_old_load_cannot_replace_newer_load():
    now = Mock(return_value=0)
    cache = ResponseCache(clock=now)
    old = cache.begin()
    now.return_value = 1
    store(cache, ("dates", "m"), b"new")
    cache.put(("dates", "m"), b"old", old.generation, old.started)
    assert cache.get(("dates", "m")) == b"new"


def test_response_and_schema_mutations_do_not_change_cache():
    cache = ResponseCache()
    session = cache.begin()
    model = GridsResponse(features=[])
    response = session.stage(("grids", ""), model)
    original = response.body
    model.type = "modified"
    response.body = b"changed"
    session.publish()
    first = session.get(("grids", ""))
    first.headers["x-test"] = "only-this-response"
    assert first.body == original
    assert "x-test" not in session.get(("grids", "")).headers


def test_concurrent_access_and_clear_are_safe():
    cache = ResponseCache(max_entries=8, max_bytes=1000)

    def request(number):
        key = ("dates", str(number % 16))
        store(cache, key, b"json")
        assert cache.get(key) in (None, b"json")
        if number % 7 == 0:
            cache.clear()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(request, range(200)))
    assert len(cache._entries) <= 8 and cache._bytes <= 1000


def test_zero_ttl_disables_cache():
    cache = ResponseCache(ttl=0)
    store(cache, ("grids", ""))
    assert cache.get(("grids", "")) is None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_cache_ttl_rejected(value):
    with pytest.raises(ValueError):
        Settings(cache_ttl_seconds=value)
    with pytest.raises(ValueError):
        ResponseCache(ttl=value)


@pytest.mark.parametrize(
    "value,expected",
    [(None, DEFAULT_CORS_ORIGINS), ("", ()), (" https://dashboard.test , ", ("https://dashboard.test",))],
)
def test_environment_overrides_default_origins(monkeypatch, value, expected):
    monkeypatch.setattr("src.api.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    if value is not None:
        monkeypatch.setenv("API_CORS_ORIGINS", value)
    monkeypatch.setenv("API_CACHE_TTL_SECONDS", "45")
    settings = Settings.from_env()
    assert settings.cors_origins == expected
    assert settings.cache_ttl_seconds == 45
    assert Settings().cors_origins == DEFAULT_CORS_ORIGINS
