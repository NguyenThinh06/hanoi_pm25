"""Persist experiment and model metadata as local JSON without database access."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.config import OUTPUTS_REGISTRY, ROOT
from src.common.storage import write_json


def compute_file_sha256(path: Path) -> str:
    """Tính mã băm SHA-256 của file artifact để đảm bảo tính toàn vẹn."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def to_rel_posix(path: Path) -> str:
    """Chuyển đường dẫn sang dạng tương đối POSIX so với thư mục gốc dự án (nếu nằm trong ROOT)."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_artifact_entry(
    *,
    artifact_id: str,
    owner_type: str,
    artifact_kind: str,
    artifact_path: Path,
    evaluation_run_id: str | None = None,
    model_id: str | None = None,
    row_count: int | None = None,
) -> dict[str, Any]:
    """Tạo bản ghi cho bảng `artifact_registry` (chỉ lưu đường dẫn và metadata, không lưu nhị phân)."""
    if owner_type == "evaluation_run" and (not evaluation_run_id or model_id is not None):
        raise ValueError("artifact của evaluation_run phải có evaluation_run_id và model_id=None.")
    if owner_type == "model" and (not model_id or evaluation_run_id is not None):
        raise ValueError("artifact của model phải có model_id và evaluation_run_id=None.")

    exists = artifact_path.exists()
    return {
        "artifact_id": artifact_id,
        "owner_type": owner_type,
        "evaluation_run_id": evaluation_run_id,
        "model_id": model_id,
        "artifact_kind": artifact_kind,
        "artifact_path": to_rel_posix(artifact_path),
        "file_size_bytes": int(artifact_path.stat().st_size) if exists else None,
        "sha256": compute_file_sha256(artifact_path) if exists else None,
        "row_count": int(row_count) if row_count is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_existing_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _upsert_records(
    existing: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    index_map: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rec in existing:
        k = tuple(rec.get(f) for f in key_fields)
        index_map[k] = rec
    for rec in new_records:
        k = tuple(rec.get(f) for f in key_fields)
        index_map[k] = rec
    return list(index_map.values())


def persist_registry_records(
    *,
    registry_dir: Path | None = None,
    evaluation_runs: list[dict[str, Any]] | None = None,
    fold_metrics: list[dict[str, Any]] | None = None,
    model_registry: list[dict[str, Any]] | None = None,
    artifact_registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Lưu trữ chuẩn hóa 4 bảng registry (`evaluation_runs`, `fold_metrics`, `model_registry`, `artifact_registry`)
    ra JSON tại `outputs/registry/`, không kết nối database hoặc chạy migration.
    """
    reg_dir = registry_dir or OUTPUTS_REGISTRY
    reg_dir.mkdir(parents=True, exist_ok=True)

    eval_path = reg_dir / "evaluation_runs.json"
    fold_path = reg_dir / "fold_metrics.json"
    model_path = reg_dir / "model_registry.json"
    art_path = reg_dir / "artifact_registry.json"
    status_path = reg_dir / "registry_status.json"

    merged_evals = _upsert_records(
        _load_existing_list(eval_path),
        evaluation_runs or [],
        ("run_id",),
    )
    merged_folds = _upsert_records(
        _load_existing_list(fold_path),
        fold_metrics or [],
        ("run_id", "model_code", "scope_type", "scope_id"),
    )
    merged_models = _upsert_records(
        _load_existing_list(model_path),
        model_registry or [],
        ("model_id",),
    )
    merged_arts = _upsert_records(
        _load_existing_list(art_path),
        artifact_registry or [],
        ("artifact_id",),
    )

    write_json(merged_evals, eval_path)
    write_json(merged_folds, fold_path)
    write_json(merged_models, model_path)
    write_json(merged_arts, art_path)

    status_payload = {
        "storage_backend": "local_json",
        "status": "saved_local",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_registry_dir": to_rel_posix(reg_dir),
        "table_counts": {
            "evaluation_runs": len(merged_evals),
            "fold_metrics": len(merged_folds),
            "model_registry": len(merged_models),
            "artifact_registry": len(merged_arts),
        },
        "files": {
            "evaluation_runs": to_rel_posix(eval_path),
            "fold_metrics": to_rel_posix(fold_path),
            "model_registry": to_rel_posix(model_path),
            "artifact_registry": to_rel_posix(art_path),
        },
    }
    write_json(status_payload, status_path)
    return status_payload
