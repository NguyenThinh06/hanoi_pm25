"""Apply database migrations and idempotently import the PM2.5 handover bundle."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pyarrow.parquet as pq
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db" / "migrations"
BUNDLE_DIR = ROOT
MANIFEST_PATH = BUNDLE_DIR / "HANDOVER_MANIFEST.json"
GRID_3405 = BUNDLE_DIR / "geometry" / "dim_grid_1km_epsg3405.parquet"
GRID_4326 = BUNDLE_DIR / "geometry" / "dim_grid_1km_epsg4326.parquet"
STATIONS = BUNDLE_DIR / "stations" / "dim_station.parquet"
OBSERVATIONS = BUNDLE_DIR / "stations" / "fct_station_daily_observations.parquet"
MODEL_DIR = BUNDLE_DIR / "metadata"
MODEL_ALIASES = {"baseline1", "baseline2"}
PREDICTION_RELATIVE_PATH = re.compile(
    r"^predictions/(baseline1|baseline2)/([^/]+)/([0-9]{4}-[0-9]{2})\.parquet$"
)


class ImportErrorWithContext(RuntimeError):
    """Raised when the handover input is incomplete or inconsistent."""


def configure_bundle(bundle_dir: Path) -> None:
    """Point all bundle inputs at an extracted bundle directory."""
    global BUNDLE_DIR, MANIFEST_PATH, GRID_3405, GRID_4326, STATIONS, OBSERVATIONS, MODEL_DIR

    BUNDLE_DIR = bundle_dir.expanduser().resolve()
    if not BUNDLE_DIR.is_dir():
        raise ImportErrorWithContext(f"Thư mục bundle không tồn tại: {BUNDLE_DIR}")
    MANIFEST_PATH = BUNDLE_DIR / "HANDOVER_MANIFEST.json"
    GRID_3405 = BUNDLE_DIR / "geometry" / "dim_grid_1km_epsg3405.parquet"
    GRID_4326 = BUNDLE_DIR / "geometry" / "dim_grid_1km_epsg4326.parquet"
    STATIONS = BUNDLE_DIR / "stations" / "dim_station.parquet"
    OBSERVATIONS = BUNDLE_DIR / "stations" / "fct_station_daily_observations.parquet"
    MODEL_DIR = BUNDLE_DIR / "metadata"


def display_bundle_path(path: Path) -> str:
    try:
        return str(path.relative_to(BUNDLE_DIR))
    except ValueError:
        return str(path)


def database_connection() -> psycopg.Connection:
    load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ImportErrorWithContext("Thiếu DATABASE_URL trong file .env.")
    # Keep each explicit transaction in the import steps as a top-level transaction.
    # This makes ON COMMIT DROP remove temporary staging tables between steps/partitions.
    return psycopg.connect(database_url, autocommit=True)


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise ImportErrorWithContext(
            "Không tìm thấy HANDOVER_MANIFEST.json. "
        )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(manifest["files"], list):
        raise ImportErrorWithContext(f"Manifest không hợp lệ: {MANIFEST_PATH}")
    return manifest

# Kiểm tra các file được liệt kê trong manifest
def check_manifest_files(manifest: dict[str, Any]) -> None:
    """Ensure every bundle path exists and retains its recorded size."""
    missing: list[str] = []
    wrong_size: list[str] = []
    for record in manifest["files"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ImportErrorWithContext(f"Đường dẫn không an toàn trong manifest: {relative}")
        path = (BUNDLE_DIR / relative).resolve()
        if not path.is_relative_to(BUNDLE_DIR):
            raise ImportErrorWithContext(f"Đường dẫn bundle vượt ra ngoài thư mục bundle: {relative}")
        if not path.is_file():
            missing.append(relative.as_posix())
        elif path.stat().st_size != record["size_bytes"]:
            wrong_size.append(relative.as_posix())
    if missing or wrong_size:
        details = []
        if missing:
            details.append(f"thiếu {len(missing)} file, ví dụ: {', '.join(missing[:5])}")
        if wrong_size:
            details.append(f"sai kích thước {len(wrong_size)} file, ví dụ: {', '.join(wrong_size[:5])}")
        raise ImportErrorWithContext("Bundle chưa đầy đủ: " + "; ".join(details))

# tạo bảng schema_migrations nếu chưa có và chạy các file migration
def apply_migrations(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        version = migration.name
        if version in applied:
            continue
        sql = migration.read_text(encoding="utf-8")
        with conn.transaction():
            for statement in sql.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        print(f"[migration] applied {version}", flush=True)

# Kiểm tra file parquet có tồn tại không và có đủ cột yêu cầu không
def require_columns(path: Path, required: set[str]) -> pq.ParquetFile:
    if not path.is_file():
        raise ImportErrorWithContext(f"Không tìm thấy file đầu vào: {display_bundle_path(path)}")
    parquet = pq.ParquetFile(path)
    missing = required - set(parquet.schema_arrow.names)
    if missing:
        raise ImportErrorWithContext(
            f"Schema {display_bundle_path(path)} thiếu cột: {', '.join(sorted(missing))}"
        )
    return parquet

# copy dữ liệu vào db, trả về số dùng đã copy
def copy_rows(cur: psycopg.Cursor, table: str, columns: tuple[str, ...], rows: Iterable[tuple[Any, ...]],) -> int:
    column_sql = ", ".join(columns)
    count = 0
    with cur.copy(f"COPY {table} ({column_sql}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count

def copy_parquet_to_stage(
    cur: psycopg.Cursor,
    path: Path,
    columns: tuple[str, ...],
    *,
    batch_size: int = 50_000,
) -> int:
    parquet = pq.ParquetFile(path)
    copied = 0
    with cur.copy(f"COPY stage_data ({', '.join(columns)}) FROM STDIN") as copy:
        for batch in parquet.iter_batches(batch_size=batch_size, columns=list(columns)):
            for row in batch.to_pylist():
                copy.write_row(tuple(row[column] for column in columns))
                copied += 1
    return copied

# ghép EPSG:3405 và EPSG:4326
def _grid_rows() -> Iterator[tuple[Any, ...]]:
    required = {"grid_id", "easting_m", "northing_m", "lon", "lat", "centroid_in_hanoi", "geometry"}
    parquet_3405 = require_columns(GRID_3405, required)
    parquet_4326 = require_columns(GRID_4326, required)
    for parquet, expected_srid, path in ((parquet_3405, 3405, GRID_3405), (parquet_4326, 4326, GRID_4326),):
        schema_metadata = parquet.schema_arrow.metadata
        if schema_metadata is None:
            raise ImportErrorWithContext(f"Thiếu metadata schema trong {display_bundle_path(path)}.")
        geo_metadata = schema_metadata.get(b"geo")
        if geo_metadata is None:
            raise ImportErrorWithContext(f"Thiếu metadata GeoParquet trong {display_bundle_path(path)}.")
        geo = json.loads(geo_metadata)
        srid = geo["columns"]["geometry"]["crs"]["id"]["code"]
        if str(srid) != str(expected_srid):
            raise ImportErrorWithContext(
                f"CRS của {display_bundle_path(path)} là {srid}, yêu cầu EPSG:{expected_srid}."
            )
    table_3405 = pq.read_table(GRID_3405, columns=sorted(required))
    table_4326 = pq.read_table(GRID_4326, columns=sorted(required))
    rows_3405 = {row["grid_id"]: row for row in table_3405.to_pylist()}
    rows_4326 = {row["grid_id"]: row for row in table_4326.to_pylist()}
    if rows_3405.keys() != rows_4326.keys():
        raise ImportErrorWithContext("Hai Parquet geometry có tập grid_id khác nhau.")
    if parquet_3405.metadata.num_rows != parquet_4326.metadata.num_rows:
        raise ImportErrorWithContext("Hai Parquet geometry có số dòng khác nhau.")
    for grid_id, row_3405 in rows_3405.items():
        row_4326 = rows_4326[grid_id]
        yield (
            grid_id,
            row_3405["easting_m"],
            row_3405["northing_m"],
            row_4326["lon"],
            row_4326["lat"],
            row_3405["centroid_in_hanoi"],
            bytes(row_3405["geometry"]),
            bytes(row_4326["geometry"]),
        )

def import_grids(conn: psycopg.Connection) -> int:
    columns = (
        "grid_id", "easting_m", "northing_m", "centroid_lon", "centroid_lat",
        "is_boundary", "geom_3405_wkb", "geom_4326_wkb",
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE stage_data (
                grid_id text PRIMARY KEY,
                easting_m bigint NOT NULL,
                northing_m bigint NOT NULL,
                centroid_lon double precision NOT NULL,
                centroid_lat double precision NOT NULL,
                is_boundary boolean NOT NULL,
                geom_3405_wkb bytea NOT NULL,
                geom_4326_wkb bytea NOT NULL
            ) ON COMMIT DROP
            """
        )
        copied = copy_rows(cur, "stage_data", columns, _grid_rows())
        cur.execute(
            """
            INSERT INTO grids (
                grid_id, easting_m, northing_m, centroid_lon, centroid_lat,
                is_boundary, geom_3405, geom_4326
            )
            SELECT grid_id, easting_m, northing_m, centroid_lon, centroid_lat,
                   is_boundary, ST_GeomFromWKB(geom_3405_wkb, 3405),
                   ST_GeomFromWKB(geom_4326_wkb, 4326)
            FROM stage_data
            ON CONFLICT (grid_id) DO UPDATE SET
                easting_m = EXCLUDED.easting_m,
                northing_m = EXCLUDED.northing_m,
                centroid_lon = EXCLUDED.centroid_lon,
                centroid_lat = EXCLUDED.centroid_lat,
                is_boundary = EXCLUDED.is_boundary,
                geom_3405 = EXCLUDED.geom_3405,
                geom_4326 = EXCLUDED.geom_4326
            """
        )
    return copied


def import_regular_parquet(
    conn: psycopg.Connection,
    source: Path,
    target: str,
    columns: tuple[str, ...],
    conflict_keys: tuple[str, ...],
    update_columns: tuple[str, ...],
) -> int:
    parquet = require_columns(source, set(columns))
    expected = parquet.metadata.num_rows
    conflict_sql = ", ".join(conflict_keys)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE stage_data (LIKE {target}) ON COMMIT DROP")
        copied = copy_parquet_to_stage(cur, source, columns)
        if copied != expected:
            raise ImportErrorWithContext(f"Đọc thiếu dòng từ {display_bundle_path(source)}.")
        cur.execute(
            f"INSERT INTO {target} ({', '.join(columns)}) "
            f"SELECT {', '.join(columns)} FROM stage_data "
            f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {updates}"
        )
    return copied


def import_stations(conn: psycopg.Connection) -> int:
    return import_regular_parquet(
        conn,
        STATIONS,
        "stations",
        ("station_id", "station_name", "lon", "lat", "grid_id", "provider", "sensor_tier", "is_boundary"),
        ("station_id",),
        ("station_name", "lon", "lat", "grid_id", "provider", "sensor_tier", "is_boundary"),
    )


def import_observations(conn: psycopg.Connection) -> int:
    return import_regular_parquet(
        conn,
        OBSERVATIONS,
        "station_daily_observations",
        (
            "station_id", "date", "station_name", "grid_id", "pm25_observed",
            "pm25_valid_hours", "is_valid_day", "pm25_std", "pm25_min", "pm25_max",
        ),
        ("station_id", "date"),
        (
            "station_name", "grid_id", "pm25_observed", "pm25_valid_hours",
            "is_valid_day", "pm25_std", "pm25_min", "pm25_max",
        ),
    )


def model_label(alias: str) -> str:
    labels = {
        "baseline1": "Baseline 1 — Khí tượng",
        "baseline2": "Baseline 2 — Khí tượng + Vệ tinh",
    }
    try:
        return labels[alias]
    except KeyError as exc:
        raise ImportErrorWithContext(f"Alias model không được hỗ trợ: {alias}") from exc


def load_model_records() -> list[tuple[Any, ...]]:
    records = []
    for alias in sorted(MODEL_ALIASES):
        path = MODEL_DIR / alias / "metadata.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        required_fields = {"model_id", "model_version", "model_name", "n_features"}
        missing_fields = required_fields - metadata.keys()
        if missing_fields:
            raise ImportErrorWithContext(
                f"Thiếu trường trong {display_bundle_path(path)}: {', '.join(sorted(missing_fields))}"
            )
        feature_count = int(metadata["n_features"])
        records.append(
            (
                metadata["model_id"],
                metadata["model_version"],
                metadata["model_name"],
                model_label(alias),
                alias == "baseline2",
                feature_count,
                Jsonb(metadata),
            )
        )
    if len(records) != 2:
        raise ImportErrorWithContext("Bundle phải có metadata cho đúng hai model.")
    with_ids = {record[0] for record in records}
    if len(with_ids) != len(records):
        raise ImportErrorWithContext("Các model trong bundle bị trùng model_id.")
    return records


def import_models(conn: psycopg.Connection) -> int:
    records = load_model_records()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE stage_data (
                model_id text PRIMARY KEY,
                model_version text NOT NULL,
                model_name text NOT NULL,
                label text NOT NULL,
                is_default boolean NOT NULL,
                feature_count integer NOT NULL,
                metadata_json jsonb NOT NULL
            ) ON COMMIT DROP
            """
        )
        copy_rows(
            cur,
            "stage_data",
            ("model_id", "model_version", "model_name", "label", "is_default", "feature_count", "metadata_json"),
            records,
        )
        cur.execute(
            """
            INSERT INTO model_metadata (
                model_id, model_version, model_name, label, is_default, feature_count, metadata_json
            )
            SELECT model_id, model_version, model_name, label, is_default, feature_count, metadata_json
            FROM stage_data
            ON CONFLICT (model_id) DO UPDATE SET
                model_version = EXCLUDED.model_version,
                model_name = EXCLUDED.model_name,
                label = EXCLUDED.label,
                is_default = EXCLUDED.is_default,
                feature_count = EXCLUDED.feature_count,
                metadata_json = EXCLUDED.metadata_json
            """
        )
    return len(records)

# chọn các file parquet cần nạp, theo tháng hoặc tất
def prediction_files(manifest: dict[str, Any], month: str | None) -> list[tuple[str, Path, str]]:
    files = []
    for record in manifest["files"]:
        match = PREDICTION_RELATIVE_PATH.match(record["path"])
        if not match:
            continue
        alias, version, partition_month = match.groups()
        if month is not None and partition_month != month:
            continue
        files.append((alias, BUNDLE_DIR / record["path"], version))
    if not files:
        raise ImportErrorWithContext(f"Manifest không có partition predictions cho tháng {month}.")
    if month is not None and {alias for alias, _, _ in files} != MODEL_ALIASES:
        raise ImportErrorWithContext(f"Tháng {month} phải có partition của cả hai model.")
    return sorted(files)

#nạp một file parquet dự đoán
def import_prediction_partition(
    conn: psycopg.Connection,
    source: Path,
    version_from_path: str,
    expected_model_id: str,
) -> int:
    columns = ("grid_id", "date", "model_id", "model_version", "pm25_pred", "run_id")
    parquet = require_columns(source, set(columns))
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE stage_data (
                grid_id text NOT NULL,
                date date NOT NULL,
                model_id text NOT NULL,
                model_version text NOT NULL,
                pm25_pred double precision NOT NULL,
                run_id text NOT NULL,
                PRIMARY KEY (grid_id, date, model_id)
            ) ON COMMIT DROP
            """
        )
        copied = copy_parquet_to_stage(cur, source, columns)
        if copied != parquet.metadata.num_rows:
            raise ImportErrorWithContext(f"Đọc thiếu dòng từ {display_bundle_path(source)}.")
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE model_id <> %s OR model_version <> %s),
                   count(*) FILTER (WHERE pm25_pred < 0),
                   count(*) FILTER (WHERE pm25_pred::text IN ('NaN', 'Infinity', '-Infinity'))
            FROM stage_data
            """,
            (expected_model_id, version_from_path),
        )
        wrong_model, negative_predictions, non_finite_predictions = cur.fetchone()
        if wrong_model:
            raise ImportErrorWithContext(
                f"{display_bundle_path(source)} chứa model_id/version không khớp metadata hoặc tên partition."
            )
        if negative_predictions:
            raise ImportErrorWithContext(f"{display_bundle_path(source)} có prediction âm.")
        if non_finite_predictions:
            raise ImportErrorWithContext(f"{display_bundle_path(source)} có prediction NaN/Infinity.")
        cur.execute(
            """
            INSERT INTO grid_daily_predictions (
                grid_id, date, model_id, model_version, pm25_pred, run_id
            )
            SELECT grid_id, date, model_id, model_version, pm25_pred, run_id
            FROM stage_data
            ON CONFLICT (grid_id, date, model_id) DO UPDATE SET
                model_version = EXCLUDED.model_version,
                pm25_pred = EXCLUDED.pm25_pred,
                run_id = EXCLUDED.run_id
            """
        )
    print(f"[predictions] {display_bundle_path(source)}: {copied:,} rows", flush=True)
    return copied

# kiểm tra sau khi nạp
def verify_counts(conn: psycopg.Connection, manifest: dict[str, Any], smoke_month: str | None) -> None:
    scope = manifest["scope_summary"]
    expected = {
        "grids": int(scope["num_grids"]),
        "stations": pq.ParquetFile(STATIONS).metadata.num_rows,
        "station_daily_observations": int(scope["station_daily_observations_count"]),
        "model_metadata": len(MODEL_ALIASES),
    }
    for table, minimum in expected.items():
        actual = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if actual != minimum:
            raise ImportErrorWithContext(f"{table}: có {actual:,} dòng, cần {minimum:,}.")
        print(f"[verify] {table}: {actual:,}", flush=True)
    if smoke_month is None:
        prediction_expected = int(scope["total_prediction_rows"])
        predicate = ""
    else:
        target_files = prediction_files(manifest, smoke_month)
        prediction_expected = sum(pq.ParquetFile(path).metadata.num_rows for _, path, _ in target_files)
        predicate = "WHERE date >= %s AND date < (%s::date + interval '1 month')"
    if predicate:
        actual_predictions = conn.execute(
            f"SELECT count(*) FROM grid_daily_predictions {predicate}",
            (date.fromisoformat(f"{smoke_month}-01"), date.fromisoformat(f"{smoke_month}-01")),
        ).fetchone()[0]
    else:
        actual_predictions = conn.execute("SELECT count(*) FROM grid_daily_predictions").fetchone()[0]
    if actual_predictions != prediction_expected:
        raise ImportErrorWithContext(
            f"grid_daily_predictions: có {actual_predictions:,} dòng, cần {prediction_expected:,}."
        )
    print(f"[verify] grid_daily_predictions: {actual_predictions:,}", flush=True)
    if smoke_month is None:
        missing_grids = conn.execute(
            """
            SELECT count(*) FROM grid_daily_predictions p
            LEFT JOIN grids g USING (grid_id) WHERE g.grid_id IS NULL
            """
        ).fetchone()[0]
        if missing_grids:
            raise ImportErrorWithContext(f"Có {missing_grids:,} prediction tham chiếu grid_id không tồn tại.")


def run_import(smoke_month: str | None, migrate_only: bool) -> None:
    manifest = None
    if not migrate_only:
        manifest = load_manifest()
        check_manifest_files(manifest)
    with database_connection() as conn:
        apply_migrations(conn)
        if migrate_only:
            print("Migration hoàn tất.")
            return
        grids = import_grids(conn)
        print(f"[import] grids: {grids:,} source rows", flush=True)
        stations = import_stations(conn)
        print(f"[import] stations: {stations:,} source rows", flush=True)
        observations = import_observations(conn)
        print(f"[import] station_daily_observations: {observations:,} source rows", flush=True)
        models = import_models(conn)
        print(f"[import] model_metadata: {models:,} source rows", flush=True)
        expected_ids = {record[0] for record in load_model_records()}
        imported_prediction_rows = 0
        for alias, path, version in prediction_files(manifest, smoke_month):
            # Alias is encoded by the manifest path; confirm it maps to the expected model.
            metadata_path = MODEL_DIR / alias / "metadata.json"
            model_id = json.loads(metadata_path.read_text(encoding="utf-8"))["model_id"]
            if model_id not in expected_ids:
                raise ImportErrorWithContext(f"Alias {alias} tham chiếu model không có metadata.")
            imported_prediction_rows += import_prediction_partition(conn, path, version, model_id)
        print(f"[import] prediction source rows: {imported_prediction_rows:,}", flush=True)
        verify_counts(conn, manifest, smoke_month)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        help="Thư mục gốc chứa HANDOVER_MANIFEST.json và các thư mục bundle (mặc định: thư mục gốc repo).",
    )
    parser.add_argument(
        "--smoke-month",
        metavar="YYYY-MM",
        help="Chỉ nạp prediction tháng này của cả hai model; các bảng dimension vẫn nạp đầy đủ.",
    )
    parser.add_argument("--migrate-only", action="store_true", help="Chỉ áp dụng các migration chưa chạy.")
    args = parser.parse_args()
    smoke_month = args.smoke_month or os.getenv("IMPORT_SMOKE_MONTH")
    if smoke_month and smoke_month.strip().lower() in ("all", "none", "false", ""):
        smoke_month = None
    if smoke_month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", smoke_month):
        parser.error(
            f"--smoke-month / IMPORT_SMOKE_MONTH phải theo định dạng YYYY-MM, ví dụ 2024-01 (nhận được: {smoke_month})"
        )
    try:
        configure_bundle(args.bundle_dir or ROOT)
        run_import(smoke_month, args.migrate_only)
    except (ImportErrorWithContext, OSError, psycopg.Error, ValueError, KeyError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
