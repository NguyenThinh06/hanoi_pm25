"""Unit & integration tests cho 3 phương pháp đánh giá, feature/leakage contract, lưu/tải model cuối và registry."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.storage import write_parquet
from src.models.train_baselines import (
    BASELINE1_FEATURES,
    BASELINE2_FEATURES,
    MODEL_B1_CODE,
    MODEL_B2_CODE,
    _assert_valid_oof,
    compute_metrics,
    evaluate_random_kfold,
    evaluate_spatial_groupkfold,
    evaluate_temporal_split,
    load_saved_xgb_model,
    predict_with_contract,
    prepare_training_dataset,
    run_all_evaluations,
    train_and_evaluate,
    train_final_models,
    validate_feature_contract,
)


def _build_synthetic_row(
    d: date,
    station_id: str,
    grid_id: str,
    *,
    aod_missing: int,
    is_valid_day: int,
    rng: np.random.Generator,
    pm25_override: float | None = None,
) -> dict[str, object]:
    st_num = int(station_id.split("_")[1])
    pm25_val = (
        float(pm25_override)
        if pm25_override is not None
        else float(22.0 + st_num * 4.0 + d.month * 1.5 + rng.normal(0.0, 1.0))
    )
    row: dict[str, object] = {
        "station_id": station_id,
        "station_name": f"Station {station_id}",
        "grid_id": grid_id,
        "date_id": int(d.strftime("%Y%m%d")),
        "date": d,
        "year": d.year,
        "month": d.month,
        "day_of_week": d.isoweekday(),
        "day_of_year": d.timetuple().tm_yday,
        "is_weekend": int(d.isoweekday() >= 6),
        "season": "winter" if d.month in (12, 1, 2) else "summer",
        "easting_m": 580000 + st_num * 1000,
        "northing_m": 2320000 + st_num * 1000,
        "is_valid_day": is_valid_day,
        "pm25_mean": pm25_val,
    }
    for col in BASELINE2_FEATURES:
        if col not in row:
            if col == "aod_047_missing":
                row[col] = int(aod_missing)
            elif col == "aod_047":
                row[col] = np.nan if aod_missing == 1 else float(rng.uniform(0.2, 0.8))
            elif col.endswith("_missing"):
                row[col] = 0
            else:
                row[col] = float(rng.normal(20.0, 3.0))
    return row


def _make_synthetic_mart_df(seed: int = 42) -> pd.DataFrame:
    """
    Tạo dữ liệu giả lập có 5 ô lưới (grid_1..grid_5) để đủ chạy 5-Fold Spatial GroupKFold,
    5-Fold Random KFold và Temporal Split qua mốc 2026-01-01.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []

    pre2026_dates = [
        date(2024, 6, 15),
        date(2024, 12, 31),
        date(2025, 6, 15),
        date(2025, 12, 31),
    ]
    for d in pre2026_dates:
        for idx in range(1, 6):
            aod_miss = 0 if (idx % 2 == 1) else 1
            rows.append(
                _build_row_alias(d, f"st_{idx}", f"grid_{idx}", aod_missing=aod_miss, is_valid_day=1, rng=rng)
            )

    # Giai đoạn >= 2026-01-01 đến ngày cuối thực tế 2026-08-20 (không hard-code 2026-09-30):
    # - st_1 (đã xuất hiện trong train, có AOD): 3 dòng
    # - st_2 (đã xuất hiện trong train, thiếu AOD): 2 dòng
    # - st_6 (trạm mới ở grid_6 chưa xuất hiện trong train, thiếu AOD): 1 dòng (để kiểm tra R2=None khi N=1)
    rows.append(_build_row_alias(date(2026, 1, 1), "st_1", "grid_1", aod_missing=0, is_valid_day=1, rng=rng))
    rows.append(_build_row_alias(date(2026, 4, 10), "st_1", "grid_1", aod_missing=0, is_valid_day=1, rng=rng))
    rows.append(_build_row_alias(date(2026, 8, 20), "st_1", "grid_1", aod_missing=0, is_valid_day=1, rng=rng))
    rows.append(_build_row_alias(date(2026, 2, 15), "st_2", "grid_2", aod_missing=1, is_valid_day=1, rng=rng))
    rows.append(_build_row_alias(date(2026, 7, 5), "st_2", "grid_2", aod_missing=1, is_valid_day=1, rng=rng))
    rows.append(_build_row_alias(date(2026, 5, 1), "st_6", "grid_6", aod_missing=1, is_valid_day=1, rng=rng))

    # Dòng không hợp lệ (is_valid_day=0) và dòng pm25_mean=NaN phải bị loại bỏ khi chuẩn bị tập train
    rows.append(_build_row_alias(date(2025, 3, 1), "st_1", "grid_1", aod_missing=0, is_valid_day=0, rng=rng))
    nan_row = _build_row_alias(date(2025, 4, 1), "st_1", "grid_1", aod_missing=0, is_valid_day=1, rng=rng)
    nan_row["pm25_mean"] = np.nan
    rows.append(nan_row)

    return pd.DataFrame(rows)


def _build_row_alias(*args, **kwargs) -> dict[str, object]:
    return _build_synthetic_row(*args, **kwargs)


def test_prepare_training_dataset_and_feature_contract():
    raw_df = _make_synthetic_mart_df()
    assert len(raw_df) == 28
    work = prepare_training_dataset(raw_df, valid_days_only=True)
    # 20 dòng trước 2026 + 6 dòng năm 2026 = 26 dòng hợp lệ
    assert len(work) == 26
    assert (work["is_valid_day"] == 1).all()
    assert work["pm25_mean"].notna().all()
    assert work.duplicated(subset=["station_id", "date_id"]).sum() == 0

    # Phát hiện trùng khóa (station_id, date_id)
    dup_df = pd.concat([work, work.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="trùng khóa chính"):
        prepare_training_dataset(dup_df, valid_days_only=True)

    # Phát hiện rò rỉ nhãn hoặc cột cảm biến trạm trong feature_list
    with pytest.raises(ValueError, match="rò rỉ nhãn"):
        validate_feature_contract(work, BASELINE1_FEATURES + ["pm25_mean"])
    with pytest.raises(ValueError, match="rò rỉ nhãn"):
        validate_feature_contract(work, BASELINE1_FEATURES + ["pm10_aq"])

    # Đảm bảo thứ tự cột của X khớp tuyệt đối với feature_list kể cả khi cột trong df bị đảo thứ tự
    shuffled_cols = list(reversed(work.columns))
    X_b1 = validate_feature_contract(work[shuffled_cols], BASELINE1_FEATURES)
    assert list(X_b1.columns) == BASELINE1_FEATURES


def test_mape_strictly_uses_positive_pm25_and_edge_cases():
    # Dòng 1: y=0.0 (phải bị loại khỏi MAPE), dòng 2: y=20.0, pred=15.0 (|e|/y = 25%), dòng 3: y=40.0, pred=50.0 (25%)
    y_true = np.array([0.0, 20.0, 40.0])
    y_pred = np.array([10.0, 15.0, 50.0])
    m = compute_metrics(y_true, y_pred)
    assert m["n_samples"] == 3
    assert m["n_mape_samples"] == 2
    assert m["mape_pct"] == pytest.approx(25.0)
    assert m["null_reason"] is None

    # Trường hợp tất cả y_true <= 0 -> n_mape_samples = 0, mape_pct = NaN kèm lý do
    m_zero = compute_metrics(np.array([0.0, 0.0]), np.array([1.0, 2.0]))
    assert m_zero["n_samples"] == 2
    assert m_zero["n_mape_samples"] == 0
    assert np.isnan(m_zero["mape_pct"])
    assert "no_positive_pm25_mean_for_mape" in m_zero["null_reason"]
    assert "zero_variance_in_y_true_for_r2" in m_zero["null_reason"]

    # Trường hợp chỉ có 1 mẫu -> R2 = NaN kèm lý do
    m_one = compute_metrics(np.array([25.0]), np.array([20.0]))
    assert m_one["n_samples"] == 1
    assert m_one["n_mape_samples"] == 1
    assert m_one["mae"] == pytest.approx(5.0)
    assert np.isnan(m_one["r2"])
    assert "insufficient_samples_for_r2" in m_one["null_reason"]

    # Nhóm rỗng
    m_empty = compute_metrics(np.array([]), np.array([]))
    assert m_empty["n_samples"] == 0
    assert m_empty["n_mape_samples"] == 0
    assert np.isnan(m_empty["mae"])
    assert m_empty["null_reason"] == "empty_group"


def test_spatial_groupkfold_no_grid_overlap_and_oof_completeness(tmp_path: Path):
    raw_df = _make_synthetic_mart_df(seed=42)
    res1 = evaluate_spatial_groupkfold(raw_df, output_dir=tmp_path / "sp1", n_splits=5, seed=42)
    res2 = evaluate_spatial_groupkfold(raw_df, output_dir=tmp_path / "sp2", n_splits=5, seed=42)

    # Tái tạo chính xác cùng kết quả khi dùng cùng seed
    pd.testing.assert_frame_equal(res1["predictions"], res2["predictions"])
    pd.testing.assert_frame_equal(res1["fold_assignments"], res2["fold_assignments"])

    pred_df = res1["predictions"]
    assert len(pred_df) == 26
    assert pred_df.duplicated(subset=["station_id", "date_id"]).sum() == 0
    # Mỗi grid_id chỉ thuộc duy nhất 1 fold_id (không overlap giữa train và validation)
    assert pred_df.groupby("grid_id")["fold_id"].nunique().max() == 1

    # Tính tay Macro-MAE không trọng số qua 6 ô và đối chiếu với metrics.json
    grid_maes_b1 = [
        float(np.mean(np.abs(g["y_true"] - g["pred_baseline1"])))
        for _, g in pred_df.groupby("grid_id")
    ]
    assert res1["metrics"]["macro_by_grid"]["baseline1_macro_mae_ug_m3"] == pytest.approx(
        round(float(np.mean(grid_maes_b1)), 4)
    )

    # Kiểm tra phát hiện lỗi nếu 1 grid_id bị gán sang 2 fold khác nhau
    work = prepare_training_dataset(raw_df)
    bad_oof = pred_df.copy()
    g1_rows = bad_oof.index[bad_oof["grid_id"] == "grid_1"].tolist()
    bad_oof.loc[g1_rows[0], "fold_id"] = (int(bad_oof.loc[g1_rows[0], "fold_id"]) + 1) % 5
    with pytest.raises(AssertionError, match="nhiều hơn 1 fold"):
        _assert_valid_oof(work, bad_oof, require_disjoint_grids_per_fold=True)


def test_random_kfold_seed_reproducibility_and_oof_completeness(tmp_path: Path):
    raw_df = _make_synthetic_mart_df(seed=42)
    rk_42_a = evaluate_random_kfold(raw_df, output_dir=tmp_path / "rk42a", n_splits=5, seed=42)
    rk_42_b = evaluate_random_kfold(raw_df, output_dir=tmp_path / "rk42b", n_splits=5, seed=42)
    rk_99 = evaluate_random_kfold(raw_df, output_dir=tmp_path / "rk99", n_splits=5, seed=99)

    pd.testing.assert_frame_equal(rk_42_a["predictions"], rk_42_b["predictions"])
    pd.testing.assert_frame_equal(rk_42_a["fold_assignments"], rk_42_b["fold_assignments"])
    # Khác seed -> phép chia KFold có shuffle khác nhau
    assert not rk_42_a["fold_assignments"]["fold_id"].equals(rk_99["fold_assignments"]["fold_id"])
    assert len(rk_42_a["predictions"]) == 26
    assert rk_42_a["predictions"].duplicated(subset=["station_id", "date_id"]).sum() == 0


def test_temporal_split_boundary_dynamic_end_date_and_empty_aod_group(tmp_path: Path):
    raw_df = _make_synthetic_mart_df(seed=42)
    tm_res = evaluate_temporal_split(raw_df, output_dir=tmp_path / "tm1", seed=42)

    sb = tm_res["metrics"]["split_boundary"]
    assert sb["max_train_date"] == "2025-12-31"
    assert sb["min_validation_date"] == "2026-01-01"
    # Ngày cuối được tính động từ dữ liệu thực (2026-08-20), không hard-code 2026-09-30
    assert sb["max_validation_date"] == "2026-08-20"
    assert sb["non_overlapping_dates_verified"] is True

    st_ov = tm_res["metrics"]["station_overlap_summary"]
    assert st_ov["validation_total_stations"] == 3
    assert st_ov["validation_stations_seen_in_train_count"] == 2
    assert st_ov["validation_stations_unseen_in_train_count"] == 1
    assert st_ov["validation_rows_from_known_stations"] == 5
    assert st_ov["validation_rows_from_unseen_stations"] == 1

    # Kiểm tra khi toàn bộ validation thiếu AOD (nhóm aod_available rỗng)
    all_missing_aod_df = raw_df.copy()
    val_rows = pd.to_datetime(all_missing_aod_df["date"]).dt.date >= date(2026, 1, 1)
    all_missing_aod_df.loc[val_rows, "aod_047_missing"] = 1
    all_missing_aod_df.loc[val_rows, "aod_047"] = np.nan

    tm_no_aod = evaluate_temporal_split(all_missing_aod_df, output_dir=tmp_path / "tm_no_aod", seed=42)
    aod_avail = tm_no_aod["metrics"]["by_aod"]["aod_available"]
    assert aod_avail["n_samples"] == 0
    assert aod_avail["baseline1"]["mae"] is None
    assert aod_avail["baseline1"]["r2"] is None
    assert aod_avail["baseline1"]["null_reason"] == "empty_group"


def test_save_load_final_models_and_artifact_metadata_persistence(tmp_path: Path):
    raw_df = _make_synthetic_mart_df(seed=42)
    marts_dir = tmp_path / "marts"
    out_root = tmp_path / "outputs"
    write_parquet(raw_df, marts_dir / "mart_station_daily_training.parquet")

    result = train_and_evaluate(
        marts_dir=marts_dir,
        outputs_root=out_root,
        n_splits=5,
        seed=42,
        valid_days_only=True,
        estimate_grid=False,
        model_version="v2.0.0-test",
    )

    # 1. Kiểm tra đủ các file của 3 phép đánh giá
    for method in ("spatial_groupkfold", "random_kfold", "temporal_split"):
        ev_dir = out_root / "evaluation" / method
        assert (ev_dir / "metrics.json").exists()
        assert (ev_dir / "predictions.parquet").exists()
        assert (ev_dir / "config.yaml").exists()
        assert (ev_dir / "metadata.json").exists()
        assign_name = "split_assignments.parquet" if method == "temporal_split" else "fold_assignments.parquet"
        assert (ev_dir / assign_name).exists()

    # 2. Kiểm tra lưu/tải 2 model cuối và tính nhất quán dự đoán trên sample
    work = prepare_training_dataset(raw_df)
    sample = work.iloc[:10].copy()

    for folder, feat_list, expected_code in [
        ("baseline1", BASELINE1_FEATURES, MODEL_B1_CODE),
        ("baseline2", BASELINE2_FEATURES, MODEL_B2_CODE),
    ]:
        m_dir = out_root / "models" / folder
        model_file = m_dir / "model.json"
        meta_file = m_dir / "metadata.json"
        cfg_file = m_dir / "config.yaml"
        sample_file = m_dir / "sample_verification_predictions.parquet"

        assert model_file.exists()
        assert meta_file.exists()
        assert cfg_file.exists()
        assert sample_file.exists()

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["model_code"] == expected_code
        assert meta["model_version"] == "v2.0.0-test"
        assert meta["feature_list"] == feat_list
        assert meta["reload_verification"]["verified"] is True
        assert set(meta["related_evaluation_runs"].keys()) == {
            "spatial_groupkfold",
            "random_kfold",
            "temporal_split",
        }

        reloaded = load_saved_xgb_model(model_file)
        preds_reloaded = predict_with_contract(reloaded, sample, feat_list)
        preds_original = predict_with_contract(result["final_models"][folder]["model"], sample, feat_list)
        np.testing.assert_allclose(preds_reloaded, preds_original, rtol=1e-6, atol=1e-6)

    # 3. Kiểm tra metadata JSON cục bộ, không phụ thuộc SQL
    reg_dir = out_root / "registry"
    assert (reg_dir / "evaluation_runs.json").exists()
    assert (reg_dir / "fold_metrics.json").exists()
    assert (reg_dir / "model_registry.json").exists()
    assert (reg_dir / "artifact_registry.json").exists()
    assert (reg_dir / "registry_status.json").exists()
    status = json.loads((reg_dir / "registry_status.json").read_text(encoding="utf-8"))
    assert status["storage_backend"] == "local_json"
    assert status["status"] == "saved_local"

    eval_runs = json.loads((reg_dir / "evaluation_runs.json").read_text(encoding="utf-8"))
    models_reg = json.loads((reg_dir / "model_registry.json").read_text(encoding="utf-8"))
    arts_reg = json.loads((reg_dir / "artifact_registry.json").read_text(encoding="utf-8"))
    assert len(eval_runs) == 3
    assert len(models_reg) == 2
    assert len(arts_reg) == 3 * 5 + 2 * 4  # 15 evaluation artifacts + 8 model artifacts = 23

    # Kiểm tra hàm train_final_models độc lập và run_all_evaluations độc lập
    standalone_eval = run_all_evaluations(
        train_path=marts_dir / "mart_station_daily_training.parquet",
        outputs_root=tmp_path / "standalone_out",
        n_splits=5,
        seed=42,
        methods=("spatial_groupkfold",),
    )
    assert "spatial_groupkfold" in standalone_eval
    standalone_models = train_final_models(
        train_path=marts_dir / "mart_station_daily_training.parquet",
        outputs_root=tmp_path / "standalone_out",
        seed=42,
        model_version="v2.0.0-standalone",
    )
    assert standalone_models["baseline1"]["metadata"]["reload_verification"]["verified"] is True
