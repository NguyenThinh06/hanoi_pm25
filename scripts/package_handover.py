"""Đóng gói và xác minh dữ liệu bàn giao cho nhóm tiếp nhận ứng dụng PM2.5 Hà Nội.

Phạm vi gói bàn giao mới:
  1. Prediction toàn bộ 2.099 ngày (01/01/2021 - 30/09/2026) của cả hai model:
       - Baseline 1 (7.577.390 dòng)
       - Baseline 2 (7.577.390 dòng)
       - Chia theo partition tháng YYYY-MM.parquet + manifest
  2. Geometry ô lưới (3.610 ô):
       - EPSG:3405 (chuẩn gốc VN-2000 UTM Zone 48N)
       - EPSG:4326 (chuyển đổi WGS84 cho bản đồ / PostGIS)
       - GeoJSON FeatureCollection
  3. Thông tin trạm và chuỗi quan trắc ngày:
       - dim_station.parquet (tọa độ, mã ô, thông tin trạm)
       - fct_station_daily_observations.parquet (9.390 bản ghi, giữ rõ cờ QC và null)
  4. Metadata và tóm tắt đánh giá của hai mô hình:
       - metadata.json, config.yaml của từng model
       - models_summary.json tổng hợp chỉ số đánh giá 3 phương pháp và giới hạn sử dụng
  5. HANDOVER_MANIFEST.json và mã checksum SHA-256 từng file

Tuyệt đối KHÔNG đóng gói:
  - raw, staging, training mart, binary model nặng hoặc OOF evaluation.
  - Các dữ liệu gốc này được bảo lưu nguyên vẹn trong kho lưu trữ dữ liệu.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
HANDOVER_BUNDLES_DIR = ROOT / "handover_bundles"
STAGING_DIR = ROOT / "outputs" / "handover_staging"
DEFAULT_BUNDLE_NAME = "pm25-handover-2026-11-04.tar.gz"


def compute_stream_sha256(stream: io.BufferedReader | io.BytesIO) -> str:
    """Tính SHA-256 của luồng dữ liệu theo block 1MB."""
    hasher = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(chunk)
    return hasher.hexdigest()


def compute_file_sha256(path: Path) -> str:
    with path.open("rb") as f:
        return compute_stream_sha256(f)


def verify_bundle(bundle_path: Path) -> dict[str, Any]:
    """Kiểm tra toàn diện tính toàn vẹn của file nén tar.gz và manifest bên trong."""
    if not bundle_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file bundle tại: {bundle_path}")

    print(f"Bắt đầu kiểm tra bundle: {bundle_path.name} ({bundle_path.stat().st_size / 1e6:.2f} MB)")
    with tarfile.open(bundle_path, "r:gz") as archive:
        try:
            manifest_file = archive.extractfile("HANDOVER_MANIFEST.json")
            if manifest_file is None:
                raise ValueError("Không tìm thấy HANDOVER_MANIFEST.json trong file nén!")
            manifest = json.load(manifest_file)
        except KeyError:
            raise ValueError("Archive thiếu file HANDOVER_MANIFEST.json")

        expected_files = {record["path"]: record for record in manifest["files"]}
        archive_names = archive.getnames()

        # Kiểm tra không có tên file lặp
        if len(archive_names) != len(set(archive_names)):
            raise ValueError("Phát hiện file bị lặp tên trong archive!")

        # Kiểm tra danh sách file khớp tuyệt đối
        expected_set = set(expected_files.keys()) | {"HANDOVER_MANIFEST.json"}
        if set(archive_names) != expected_set:
            diff_missing = expected_set - set(archive_names)
            diff_extra = set(archive_names) - expected_set
            raise ValueError(f"Danh sách file không khớp manifest! Thiếu: {diff_missing}, Thừa: {diff_extra}")

        # Kiểm tra kích thước và checksum từng file
        print(f"  + Đang kiểm tra checksum {len(expected_files)} files...")
        for rel_path, record in expected_files.items():
            member = archive.getmember(rel_path)
            if not member.isfile():
                raise ValueError(f"Thành phần trong archive không phải file thường: {rel_path}")
            if member.size != record["size_bytes"]:
                raise ValueError(
                    f"Sai kích thước file {rel_path}: kỳ vọng {record['size_bytes']}, thực tế {member.size}"
                )
            file_stream = archive.extractfile(member)
            if file_stream is None:
                raise ValueError(f"Không thể đọc file: {rel_path}")
            actual_sha = compute_stream_sha256(file_stream)
            if actual_sha != record["sha256"]:
                raise ValueError(
                    f"Checksum không khớp cho {rel_path}!\n  Kỳ vọng: {record['sha256']}\n  Thực tế: {actual_sha}"
                )

    print(f"XÁC MINH THÀNH CÔNG: {bundle_path.name} ({len(expected_files)} files hợp lệ 100%)")
    return manifest


def collect_handover_files() -> list[tuple[Path, str]]:
    """Thu thập danh sách tất cả file cần đóng gói và đường dẫn tương đối trong archive."""
    collected: list[tuple[Path, str]] = []

    # 1. Predictions
    pred_root = ROOT / "outputs" / "predictions"
    if not pred_root.exists():
        raise FileNotFoundError(f"Không tìm thấy thư mục predictions tại {pred_root}")

    for model_alias in ["baseline1", "baseline2"]:
        model_pred_dir = pred_root / model_alias / "v2.0.0-retrospective"
        if not model_pred_dir.exists():
            raise FileNotFoundError(f"Thiếu thư mục prediction: {model_pred_dir}")

        for p_file in sorted(model_pred_dir.glob("*.parquet")):
            arc_name = f"predictions/{model_alias}/v2.0.0-retrospective/{p_file.name}"
            collected.append((p_file, arc_name))

        manifest_file = model_pred_dir / "manifest.json"
        if manifest_file.exists():
            arc_name = f"predictions/{model_alias}/v2.0.0-retrospective/manifest.json"
            collected.append((manifest_file, arc_name))

    # 2. Geometry
    geom_dir = STAGING_DIR / "geometry"
    if not geom_dir.exists():
        raise FileNotFoundError(f"Thiếu thư mục geometry tại {geom_dir}. Hãy chạy chuẩn bị trước!")
    for g_file in sorted(geom_dir.glob("*")):
        if g_file.is_file():
            collected.append((g_file, f"geometry/{g_file.name}"))

    # 3. Stations
    stations_dir = STAGING_DIR / "stations"
    if not stations_dir.exists():
        raise FileNotFoundError(f"Thiếu thư mục stations tại {stations_dir}. Hãy chạy chuẩn bị trước!")
    for s_file in sorted(stations_dir.glob("*")):
        if s_file.is_file():
            collected.append((s_file, f"stations/{s_file.name}"))

    # 4. Metadata
    meta_dir = STAGING_DIR / "metadata"
    if not meta_dir.exists():
        raise FileNotFoundError(f"Thiếu thư mục metadata tại {meta_dir}. Hãy chạy chuẩn bị trước!")
    for m_file in sorted(meta_dir.rglob("*")):
        if m_file.is_file():
            rel = m_file.relative_to(meta_dir).as_posix()
            collected.append((m_file, f"metadata/{rel}"))

    return collected


def build_handover_bundle(
    bundle_name: str = DEFAULT_BUNDLE_NAME,
    clean_old_bundles: bool = False,
) -> Path:
    """Tạo gói dữ liệu bàn giao mới tại thư mục staging, kiểm tra checksum rồi chuyển vào handover_bundles/."""
    print("================================================================================")
    print("BẮT ĐẦU ĐÓNG GÓI DỮ LIỆU BÀN GIAO MỚI")
    print("================================================================================")

    # Đảm bảo các artifact phụ trợ đã được sinh đầy đủ
    if not (STAGING_DIR / "geometry" / "dim_grid_1km_epsg4326.parquet").exists():
        print("Đang chạy chuẩn bị artifact phụ trợ...")
        from src.common.config import ROOT as PROJ_ROOT
        script_prep = PROJ_ROOT / "scripts" / "prepare_handover_artifacts.py"
        if script_prep.exists():
            subprocess.run([sys.executable, str(script_prep)], check=True)

    file_entries = collect_handover_files()
    print(f"Tổng số file cần đóng gói: {len(file_entries)}")

    # Tính checksum của từng file
    records: list[dict[str, Any]] = []
    total_uncompressed_bytes = 0
    for src_path, arc_path in file_entries:
        sz = src_path.stat().st_size
        total_uncompressed_bytes += sz
        sha = compute_file_sha256(src_path)
        records.append(
            {
                "path": arc_path,
                "size_bytes": sz,
                "sha256": sha,
            }
        )

    # Lấy thông tin git commit hiện tại
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        git_commit = "unknown"

    manifest_data = {
        "title": "Hanoi PM2.5 Grid-Level Retrospective Predictions Handover Bundle",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bundle_name": bundle_name,
        "source_git_commit": git_commit,
        "scope_summary": {
            "spatial_resolution": "1 km x 1 km grid (EPSG:3405 / EPSG:4326)",
            "num_grids": 3610,
            "temporal_range": {
                "start_date": "2021-01-01",
                "end_date": "2026-09-30",
                "num_days": 2099,
            },
            "models": [
                {
                    "alias": "baseline1",
                    "model_id": "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective",
                    "model_version": "v2.0.0-retrospective",
                    "prediction_rows": 7577390,
                },
                {
                    "alias": "baseline2",
                    "model_id": "Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective",
                    "model_version": "v2.0.0-retrospective",
                    "prediction_rows": 7577390,
                },
            ],
            "total_prediction_rows": 15154780,
            "stations_count": 39,
            "station_daily_observations_count": 9390,
        },
        "total_files": len(records),
        "total_uncompressed_bytes": total_uncompressed_bytes,
        "files": records,
    }

    manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, indent=2).encode("utf-8")

    # Tạo file tar.gz trong thư mục staging riêng biệt
    staging_bundle_dir = STAGING_DIR / "_bundle_staging"
    staging_bundle_dir.mkdir(parents=True, exist_ok=True)
    temp_bundle_path = staging_bundle_dir / f"{bundle_name}.tmp"

    print(f"Đang ghi file archive tạm: {temp_bundle_path}...")
    with tarfile.open(temp_bundle_path, "w:gz", compresslevel=6) as archive:
        for src_path, arc_path in file_entries:
            archive.add(src_path, arcname=arc_path, recursive=False)

        # Thêm file HANDOVER_MANIFEST.json vào root của archive
        tinfo = tarfile.TarInfo("HANDOVER_MANIFEST.json")
        tinfo.size = len(manifest_bytes)
        tinfo.mtime = int(datetime.now(timezone.utc).timestamp())
        archive.addfile(tinfo, io.BytesIO(manifest_bytes))

    # Đổi tên file tạm thành bundle hoàn chỉnh trong staging
    staged_bundle = staging_bundle_dir / bundle_name
    temp_bundle_path.replace(staged_bundle)

    # Xác minh tính toàn vẹn và checksum của bundle vừa tạo trong staging
    print("\nĐang xác minh bundle vừa tạo trong staging...")
    verify_bundle(staged_bundle)
    staged_sha256 = compute_file_sha256(staged_bundle)
    staged_size = staged_bundle.stat().st_size
    print(f"Checksum bundle mới: {staged_sha256} ({staged_size / 1e6:.2f} MB)")

    # Sau khi xác minh thành công 100%, mới tiến hành thay thế tại handover_bundles/
    HANDOVER_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)

    if clean_old_bundles:
        print("\nTiến hành dọn dẹp các gói bàn giao cũ trong handover_bundles/...")
        for old_file in HANDOVER_BUNDLES_DIR.glob("*"):
            if old_file.is_file():
                print(f"  - Xóa gói cũ: {old_file.name}")
                old_file.unlink()

    final_bundle_path = HANDOVER_BUNDLES_DIR / bundle_name
    staged_bundle.replace(final_bundle_path)

    # Ghi file .sha256 và .manifest.json đi kèm
    sha_file = final_bundle_path.with_name(f"{bundle_name}.sha256")
    sha_file.write_text(f"{staged_sha256}  {bundle_name}\n", encoding="utf-8")

    manifest_out = final_bundle_path.with_name(f"{bundle_name}.manifest.json")
    manifest_out.write_bytes(manifest_bytes)

    print("\n================================================================================")
    print("HOÀN THÀNH ĐÓNG GÓI DỮ LIỆU BÀN GIAO THÀNH CÔNG!")
    print(f"  + Đường dẫn: {final_bundle_path.resolve()}")
    size_mb = final_bundle_path.stat().st_size / 1e6
    size_bytes = final_bundle_path.stat().st_size
    print(f"  + Dung lượng: {size_mb:.2f} MB ({size_bytes:,} bytes)")
    print(f"  + SHA-256: {staged_sha256}")
    print(f"  + File checksum: {sha_file.resolve()}")
    print(f"  + File manifest: {manifest_out.resolve()}")
    print("================================================================================\n")
    return final_bundle_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đóng gói hoặc xác minh gói dữ liệu bàn giao PM2.5 Hà Nội."
    )
    parser.add_argument(
        "--verify",
        type=Path,
        default=None,
        help="Đường dẫn file .tar.gz cần kiểm tra",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Tạo gói bàn giao mới từ dữ liệu hiện có",
    )
    parser.add_argument(
        "--bundle-name",
        type=str,
        default=DEFAULT_BUNDLE_NAME,
        help=f"Tên file bundle (mặc định: {DEFAULT_BUNDLE_NAME})",
    )
    parser.add_argument(
        "--replace-old",
        action="store_true",
        help="Xóa các file gói cũ trong handover_bundles/ sau khi gói mới xác minh đạt",
    )
    args = parser.parse_args()

    if args.verify:
        verify_bundle(args.verify)
    elif args.build:
        build_handover_bundle(bundle_name=args.bundle_name, clean_old_bundles=args.replace_old)
    else:
        # Mặc định: build và verify
        build_handover_bundle(bundle_name=args.bundle_name, clean_old_bundles=args.replace_old)


if __name__ == "__main__":
    main()
