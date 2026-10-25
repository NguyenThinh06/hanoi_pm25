"""Validate the handoff against the committed boundary and contract."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import polars as pl
import pytest
from shapely.geometry import box

from src.common.spatial_spine import generate_hanoi_grid
from src.features.build_dim_date import build_dim_date

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def generated_spine(tmp_path_factory):
    work = tmp_path_factory.mktemp("spine")
    grid, manifest = generate_hanoi_grid(
        boundary_path=ROOT / "data/reference/hanoi_boundary.geojson",
        manifest_path=work / "manifest.json",
        output_parquet=work / "grid.parquet",
    )
    dates = build_dim_date(work / "date.parquet")
    return grid, dates, manifest, work


def test_frozen_grid_and_boundary(generated_spine):
    grid, _, manifest, work = generated_spine
    frozen = json.loads((ROOT / "data/manifests/grid_manifest.json").read_text())
    boundary = ROOT / "data/reference/hanoi_boundary.geojson"
    assert hashlib.sha256(boundary.read_bytes()).hexdigest() == frozen["boundary_sha256"]
    real = grid[grid.grid_id != "grid_unknown"]
    assert len(grid) == 3611
    assert len(real) == manifest["analysis_grid_count"] == 3610
    assert grid.grid_id.is_unique and grid.grid_id.notna().all()
    assert grid.crs.to_epsg() == 3405
    assert real.geometry.is_valid.all()
    assert (real.geometry.area == 1_000_000).all()
    assert (real.area_in_boundary_km2 > 0).all()
    assert manifest["boundary_touch_only_cells"] == 0
    assert int(real.is_canonical.sum()) == 3363
    assert grid[grid.grid_id == "grid_unknown"].geometry.isna().all()
    for key, value in frozen.items():
        if key != "boundary_file":
            assert manifest[key] == value, key
    restored = gpd.read_parquet(work / "grid.parquet")
    assert restored.grid_id.tolist() == grid.grid_id.tolist()
    assert restored.geometry.equals(grid.geometry)


def test_daily_keys_leap_day_and_unknown(generated_spine):
    _, dates, manifest, work = generated_spine
    real = dates.filter(pl.col("date_id") != -1)
    assert len(dates) == manifest["dim_date_rows"] == 1827
    assert dates["date_id"].null_count() == 0
    assert dates["date_id"].n_unique() == len(dates)
    assert dates["date_id"].dtype == pl.Int32
    assert len(real) == manifest["real_days"] == 1826
    assert real["date_actual"].to_list() == [
        date(2021, 1, 1) + timedelta(days=i) for i in range(1826)
    ]
    assert real["date_id"].to_list() == [
        int(day.strftime("%Y%m%d")) for day in real["date_actual"]
    ]
    assert real.filter(pl.col("date_id") == 20240229)["date_actual"].to_list() == [date(2024, 2, 29)]
    unknown = dates.filter(pl.col("date_id") == -1)
    assert len(unknown) == 1
    assert unknown["date_actual"].item() == date(1970, 1, 1)
    assert pl.read_parquet(work / "date.parquet").equals(dates)


def test_analysis_cross_product(generated_spine):
    grid, dates, manifest, _ = generated_spine
    grid_ids = pl.DataFrame({"grid_id": grid.loc[grid.grid_id != "grid_unknown", "grid_id"].tolist()})
    days = dates.filter(pl.col("date_id") != -1).select("date_id")
    spine = grid_ids.join(days, how="cross")
    assert spine.height == manifest["expected_grid_day_rows"] == 6_591_860
    assert spine.select(pl.struct("grid_id", "date_id").n_unique()).item() == spine.height


def test_touch_only_is_explicit_and_unknown_has_no_geometry(tmp_path):
    # Middle cell touches x=1000 only; the third cell sets the outer bound.
    boundary = tmp_path / "boundary.geojson"
    gpd.GeoDataFrame(geometry=[box(100, 100, 1000, 200), box(2100, 100, 2200, 200)], crs=3405).to_file(boundary)
    grid, manifest = generate_hanoi_grid(
        boundary_path=boundary, manifest_path=tmp_path / "manifest.json",
        output_parquet=tmp_path / "grid.parquet",
    )
    assert manifest["analysis_grid_count"] == 3
    assert manifest["boundary_touch_only_cells"] == 1
    assert grid.loc[grid.grid_id == "grid_1000_0", "area_in_boundary_km2"].item() == 0
    assert grid.iloc[-1].grid_id == "grid_unknown"
    assert grid.iloc[-1].geometry is None


def test_reject_nonstandard_cell_size():
    with pytest.raises(ValueError, match="1000"):
        generate_hanoi_grid(cell_size_m=500)


def test_intersects_includes_touching_cells_on_outer_edges(tmp_path):
    boundary = tmp_path / "aligned.geojson"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1000, 1000)], crs=3405).to_file(boundary)
    grid, manifest = generate_hanoi_grid(
        boundary_path=boundary, manifest_path=tmp_path / "manifest.json",
        output_parquet=tmp_path / "grid.parquet",
    )
    assert manifest["analysis_grid_count"] == 9
    assert manifest["boundary_touch_only_cells"] == 8
    assert set(grid.grid_id) == {
        f"grid_{x}_{y}" for x in [-1000, 0, 1000] for y in [-1000, 0, 1000]
    } | {"grid_unknown"}


def test_boundary_provenance_matches_reference():
    provenance = json.loads((ROOT / "data/reference/hanoi_boundary.provenance.json").read_text(encoding="utf-8"))
    raw = (ROOT / provenance["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance["sha256"]
    feature = json.loads(raw)["features"]
    assert len(feature) == 1
    assert feature[0]["properties"]["adm1_pcode"] == "VN01"
    assert feature[0]["properties"]["adm1_name"] == "Ha Noi"
    assert provenance["verification_status"] == "verified_against_publisher_archive"
