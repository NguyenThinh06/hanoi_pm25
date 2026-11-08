"""One bounded psycopg pool per API process; no migrations or data writes."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout, TooManyRequests

from .config import Settings
from .errors import DATABASE_MESSAGE, INTERNAL_MESSAGE, APIError

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, settings: Settings):
        self.pool: ConnectionPool | None = None
        if settings.database_url:
            self.pool = ConnectionPool(
                conninfo=settings.database_url,
                min_size=settings.pool_min_size,
                max_size=settings.pool_max_size,
                timeout=settings.pool_timeout,
                max_waiting=64,
                open=False,
                check=ConnectionPool.check_connection,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": settings.connect_timeout,
                    "application_name": "hanoi_pm25_api",
                    "options": (
                        "-c default_transaction_read_only=on "
                        "-c timezone=Asia/Ho_Chi_Minh "
                        f"-c statement_timeout={settings.statement_timeout_ms}"
                    ),
                },
            )

    def open(self) -> None:
        if self.pool is not None:
            # Start even when PostgreSQL is offline; /health then returns contract 503.
            self.pool.open(wait=False)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        if self.pool is None:
            raise APIError(503, "DATABASE_UNAVAILABLE", DATABASE_MESSAGE)
        try:
            with self.pool.connection() as conn:
                yield conn
        except (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout, PoolClosed, TooManyRequests) as exc:
            logger.warning("Database request failed (%s)", type(exc).__name__)
            raise APIError(503, "DATABASE_UNAVAILABLE", DATABASE_MESSAGE) from exc
        except psycopg.Error as exc:
            # Bad SQL, permissions or stored data are not a temporary connection outage.
            # Request validation rejects unsupported identifiers before SQL adaptation.
            logger.error("Database operation failed (%s)", type(exc).__name__)
            raise APIError(500, "INTERNAL_ERROR", INTERNAL_MESSAGE) from exc
