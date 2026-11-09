"""Unit tests cho module suy luận độc lập (inference), kiểm tra hợp đồng đặc trưng,
tính toàn vẹn của partition, resume an toàn và kiểm tra tính hợp lệ của JSON mẫu trong HANDOVER.md.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.config import ROOT
from src.models.inference import (
    load_model_and_metadata,
    predict_batch,
    run_single_model_inference,
    validate_and_prepare_features,
    verify_partition_file,
)


def test_feature_contract_leakage_and_order(tmp_path: Path) -> None:
    """Kiểm tra hợp đồng đặc trưng: chống rò rỉ nhãn và kiểm soát thứ tự cột."""
    meta_dir = tmp_path / "model_leak"
    meta_dir.mkdir()
    (meta_dir / "model.json").write_text("{}", encoding="utf-8")

    # 1. Feature list chứa cột cấm pm25_mean -> phải báo lỗi
    meta_leak = {
        "model_id": "test:v1",
        "model_version": "v1",
        "feature_list": ["year", "pm25_mean", "temp_2m_c"],
    }
    (meta_dir / "metadata.json").write_text(json.dumps(meta_leak), encoding="utf-8")

    with pytest.raises(ValueError, match="Phát hiện rò rỉ nhãn"):
        load_model_and_metadata(meta_dir)

    # 2. DataFrame thiếu cột đặc trưng bắt buộc -> phải báo lỗi
    df_missing = pd.DataFrame({"year": [2021], "month": [1]})
    with pytest.raises(ValueError, match="thiếu các cột đặc trưng bắt buộc"):
        validate_and_prepare_features(df_missing, ["year", "month", "temp_2m_c"])

    # 3. Ép kiểu float64 và giữ nguyên NaN
    df_valid = pd.DataFrame(
        {
            "year": [2021, 2022],
            "temp_2m_c": [25.5, np.nan],
            "other_col": ["a", "b"],
        }
    )
    X = validate_and_prepare_features(df_valid, ["temp_2m_c", "year"])
    assert list(X.columns) == ["temp_2m_c", "year"]
    assert X["temp_2m_c"].dtype == np.float64
    assert np.isnan(X["temp_2m_c"].iloc[1])


def test_model_reload_and_prediction_match() -> None:
    """Kiểm tra tải lại model từ outputs/models/ và dự đoán khớp mẫu kiểm chứng."""
    model_dir = ROOT / "outputs" / "models" / "baseline1"
    model_file = model_dir / "model.json"
    metadata_file = model_dir / "metadata.json"
    if not model_file.exists() or not metadata_file.exists():
        pytest.skip(f"Bỏ qua vì chưa có artifact model tại {model_dir} (môi trường CI)")
    model, metadata = load_model_and_metadata(model_dir)

    assert metadata["model_id"] == "Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective"
    assert metadata["model_version"] == "v2.0.0-retrospective"
    assert len(metadata["feature_list"]) == 27

    # Đối chiếu với sample_verification_predictions.parquet đã lưu
    sample_file = model_dir / "sample_verification_predictions.parquet"
    if sample_file.exists():
        sample_df = pd.read_parquet(sample_file)
        training_mart = ROOT / "data" / "marts" / "mart_station_daily_training.parquet"
        if training_mart.exists():
            train_df = pd.read_parquet(training_mart)
            merged = train_df.merge(sample_df[["station_id", "date_id"]], on=["station_id", "date_id"])
            re_pred = predict_batch(model, merged, metadata["feature_list"])
            max_diff = np.max(np.abs(re_pred - sample_df["pred_after_reload"].to_numpy()))
            assert max_diff < 1e-6, f"Sai lệch dự đoán sau reload vượt ngưỡng: {max_diff}"


def test_batch_inference_atomic_and_resume(tmp_path: Path) -> None:
    """Kiểm tra quy trình suy luận batch, ghi file nguyên tử và resume an toàn."""
    model_dir = ROOT / "outputs" / "models" / "baseline1"
    data_path = ROOT / "data" / "marts" / "mart_grid_daily_features.parquet"

    if not (model_dir / "model.json").exists() or not (model_dir / "metadata.json").exists():
        pytest.skip(f"Bỏ qua vì chưa có artifact model tại {model_dir} (môi trường CI)")
    if not data_path.exists():
        pytest.skip("Chưa có mart_grid_daily_features.parquet để test inference")

    out_dir = tmp_path / "test_preds"

    # Chạy inference trên 2 ngày (01/01/2021 đến 02/01/2021)
    manifest = run_single_model_inference(
        model_alias="baseline1",
        model_dir=model_dir,
        data_path=data_path,
        output_root=out_dir,
        start_date=date(2021, 1, 1),
        end_date=date(2021, 1, 2),
        run_id="test_run_001",
        resume=True,
    )

    assert manifest["status"] == "COMPLETED"
    assert manifest["inference_configuration"]["total_rows"] == 3610 * 2
    assert manifest["inference_configuration"]["num_grids"] == 3610

    part_file = out_dir / "baseline1" / "v2.0.0-retrospective" / "2021-01.parquet"
    assert part_file.exists()
    assert verify_partition_file(
        part_file,
        expected_model_id="Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective",
        expected_model_version="v2.0.0-retrospective",
    )

    # Đọc lại partition kiểm tra schema
    df_part = pd.read_parquet(part_file)
    assert set(df_part.columns) == {"grid_id", "date", "model_id", "model_version", "pm25_pred", "run_id"}
    assert len(df_part) == 3610 * 2
    assert (df_part["pm25_pred"] >= 0.0).all()
    assert not df_part["pm25_pred"].isna().any()

    # Kiểm tra khóa duy nhất (grid_id, date, model_id)
    dup = df_part.duplicated(subset=["grid_id", "date", "model_id"]).sum()
    assert dup == 0

    # Chạy lại với resume=True -> file cũ phải được tái sử dụng nguyên vẹn
    mtime_before = part_file.stat().st_mtime
    manifest_resume = run_single_model_inference(
        model_alias="baseline1",
        model_dir=model_dir,
        data_path=data_path,
        output_root=out_dir,
        start_date=date(2021, 1, 1),
        end_date=date(2021, 1, 2),
        run_id="test_run_002",
        resume=True,
    )
    assert manifest_resume["status"] == "COMPLETED"
    assert part_file.stat().st_mtime == mtime_before, "Partition đáng lẽ phải được giữ nguyên khi resume!"


def test_handover_md_json_samples_are_valid() -> None:
    """Kiểm tra tất cả các khối JSON mẫu trong HANDOVER.md đều có cú pháp JSON hợp lệ."""
    handover_path = ROOT / "archive" / "HANDOVER.md"
    if not handover_path.exists():
        handover_path = ROOT / "docs" / "HANDOVER.md"
    if not handover_path.exists():
        pytest.skip("Chưa có file HANDOVER.md để kiểm thử JSON mẫu")

    content = handover_path.read_text(encoding="utf-8")

    # Tìm tất cả các khối ```json ... ``` (kể cả có thụt đầu dòng)
    pattern = re.compile(r"^[ \t]*```json\s*\n(.*?)\n[ \t]*```", re.DOTALL | re.MULTILINE)
    matches = pattern.findall(content)

    assert len(matches) >= 5, f"Kỳ vọng ít nhất 5 khối JSON mẫu trong HANDOVER.md, tìm thấy {len(matches)}"

    for idx, json_str in enumerate(matches, 1):
        # Một số JSON mẫu minh họa có thể chứa "..." ở dòng danh sách ngày, ta bỏ qua hoặc thay thế để kiểm tra
        clean_str = json_str
        if '"..."' in clean_str:
            clean_str = clean_str.replace('"..."', '"2026-09-30"')
        try:
            parsed = json.loads(clean_str)
            assert isinstance(parsed, (dict, list))
        except json.JSONDecodeError as e:
            pytest.fail(f"Lỗi cú pháp JSON tại khối mẫu thứ {idx} trong HANDOVER.md: {e}\nNội dung:\n{json_str}")
