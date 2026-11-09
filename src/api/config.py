"""API settings, independent of the data pipeline and its optional dependencies."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://localhost:3000")


@dataclass(frozen=True)
class Settings:
    database_url: str | None = field(default=None, repr=False)
    pool_min_size: int = 0
    pool_max_size: int = 8
    pool_timeout: float = 3.0
    connect_timeout: int = 3
    statement_timeout_ms: int = 5000
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    cache_ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not 0 <= self.pool_min_size <= self.pool_max_size or self.pool_max_size < 1:
            raise ValueError("API_DB_POOL_MIN/MAX không hợp lệ.")
        if not math.isfinite(self.pool_timeout) or self.pool_timeout <= 0:
            raise ValueError("API_DB_POOL_TIMEOUT phải là số hữu hạn lớn hơn 0.")
        if self.connect_timeout < 1 or self.statement_timeout_ms < 1:
            raise ValueError("Thời gian chờ Database phải lớn hơn 0.")
        if not math.isfinite(self.cache_ttl_seconds) or self.cache_ttl_seconds < 0:
            raise ValueError("API_CACHE_TTL_SECONDS phải là số hữu hạn không âm.")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL") or None,
            pool_min_size=int(os.getenv("API_DB_POOL_MIN", "0")),
            pool_max_size=int(os.getenv("API_DB_POOL_MAX", "8")),
            pool_timeout=float(os.getenv("API_DB_POOL_TIMEOUT", "3")),
            connect_timeout=int(os.getenv("API_DB_CONNECT_TIMEOUT", "3")),
            statement_timeout_ms=int(os.getenv("API_DB_STATEMENT_TIMEOUT_MS", "5000")),
            cors_origins=tuple(
                x.strip() for x in os.getenv("API_CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS)).split(",") if x.strip()
            ),
            cache_ttl_seconds=float(os.getenv("API_CACHE_TTL_SECONDS", "300")),
        )
