# Báo cáo Kiểm định Giả thuyết bằng Mô hình XGBoost & Ước tính 7,57 Triệu Ô-Ngày Hà Nội (2021–2026)

Tài liệu này báo cáo kết quả kiểm định hai giả thuyết mô hình (**H5** và **H6** trong [`docs/business_case.md`](./business_case.md)) bằng thuật toán **XGBoost** ([`src/models/train_baselines.py`](../src/models/train_baselines.py)) sau khi áp dụng quy tắc QC giờ nhị phân (`qc_flag`: `0` = hợp lệ, `1` = không hợp lệ / ngoài ngưỡng vật lý) và kết quả ước tính ($\text{estimate}$) nồng độ bụi mịn $\text{PM}_{2.5}$ trên toàn bộ **7.577.390 ô-ngày** của thành phố Hà Nội.

---

## 1. Thiết kế Thực nghiệm (Experimental Setup)

- **Tập dữ liệu huấn luyện & kiểm định:** [`data/marts/mart_station_daily_training.parquet`](../data/marts/mart_station_daily_training.parquet) (`9.207` dòng trạm-ngày có nhãn).
  - Lọc các ngày đạt chuẩn chất lượng quan trắc (`is_valid_day = 1`, có $\ge 18\text{ giờ}$ hợp lệ `qc_flag = 0` trong ngày): **$N = 7.290$ dòng trạm-ngày** trên **36 ô lưới** có trạm trong ranh giới Hà Nội (`is_boundary = TRUE`).
  - Nhãn mục tiêu ($y$): `pm25_mean` ($\mu\text{g/m}^3$), tính bằng trung bình cộng trên số giờ hợp lệ trong ngày theo giờ địa phương (`UTC+7`).
- **Hai cấu hình đặc trưng được so sánh (không dùng nội suy IDW):**
  1. **Baseline 1 (`OpenAQ + Khí tượng` — 27 đặc trưng):**
     - *Lịch & Tọa độ (7 biến):* `year`, `month`, `day_of_week`, `day_of_year`, `is_weekend`, `easting_m`, `northing_m`.
     - *Khí tượng ERA5-Land & ERA5 BLH (20 biến):* `temp_2m_c`, `dewpoint_2m_c`, `rh_pct`, `precip_mm`, `wind_speed_10m_ms`, `wind_u_10m_ms`, `wind_v_10m_ms`, `wind_persistence`, `wind_dir_10m_deg`, `surface_pressure_hpa`, `blh_mean_m`, `blh_min_m` cùng 8 cờ báo khuyết `*_missing`.
  2. **Baseline 2 (`OpenAQ + Khí tượng + Vệ tinh` — 34 đặc trưng):**
     - Toàn bộ **27 đặc trưng của Baseline 1** +
     - *Viễn thám Vệ tinh (7 biến):* `no2_trop_mol_m2`, `co_mol_m2`, `o3_mol_m2`, `so2_mol_m2` (Sentinel-5P), `aod_047`, `aod_047_missing` (MODIS MAIAC 1 km), và `viirs_radiance` (VIIRS DNB 1 km).
- **Cấu hình mô hình XGBoost chung cho cả 2 Baseline:**
  - `XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6, min_child_weight=5, subsample=0.8, colsample_bytree=0.8, reg_alpha=0.5, reg_lambda=2.0, tree_method="hist")`.

---

## 2. Kiểm định Giả thuyết H5: Khả năng Học & Dự báo trên Tập Trạm (Train Fit & 5-Fold CV)

> **Phát biểu H5:** Bổ sung dữ liệu vệ tinh (**Baseline 2**) giúp mô hình XGBoost học tốt hơn và đạt sai số dự báo 5-Fold CV thấp hơn có ý nghĩa thống kê so với chỉ sử dụng dữ liệu khí tượng (**Baseline 1**).

### 2.1. Kết quả Tổng thể trên Tập Huấn luyện & 5-Fold Cross-Validation

| Chế độ đánh giá | Mô hình | Số mẫu ($N$) | RMSE ($\mu\text{g/m}^3$) $\downarrow$ | MAE ($\mu\text{g/m}^3$) $\downarrow$ | $R^2$ $\uparrow$ | MAPE (%) $\downarrow$ |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Train Fit** | **Baseline 1: OpenAQ + Khí tượng** | 7.290 | 4.8391 | 3.3999 | 0.9622 | 12.05% |
| **Train Fit** | **Baseline 2: OpenAQ + Khí tượng + Vệ tinh** | 7.290 | **4.3853** | **3.0952** | **0.9690** | **11.01%** |
| **5-Fold CV** | **Baseline 1: OpenAQ + Khí tượng** | 7.290 | 10.1933 | 6.7355 | 0.8324 | 22.08% |
| **5-Fold CV** | **Baseline 2: OpenAQ + Khí tượng + Vệ tinh** | 7.290 | **9.9352** | **6.5798** | **0.8408** | **21.45%** |

### 2.2. Kết quả 5-Fold CV Phân tách theo 4 Mùa

| Mùa (`season`) | Số mẫu ($N$) | Mô hình | RMSE ($\mu\text{g/m}^3$) $\downarrow$ | MAE ($\mu\text{g/m}^3$) $\downarrow$ | $R^2$ $\uparrow$ | MAPE (%) $\downarrow$ |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| **Mùa xuân (`spring`)** | 1.304 | Baseline 1: OpenAQ + Khí tượng | 10.6559 | 7.3208 | 0.6734 | 21.63% |
| **Mùa xuân (`spring`)** | 1.304 | **Baseline 2: + Vệ tinh** | **10.2470** | **7.0537** | **0.6980** | **20.87%** |
| **Mùa hạ (`summer`)** | 2.216 | Baseline 1: OpenAQ + Khí tượng | 7.4715 | 4.8669 | 0.6360 | 23.95% |
| **Mùa hạ (`summer`)** | 2.216 | **Baseline 2: + Vệ tinh** | **7.4149** | 4.8882 | **0.6415** | **23.81%** |
| **Mùa thu (`autumn`)** | 1.220 | Baseline 1: OpenAQ + Khí tượng | 7.9111 | 5.7215 | 0.7806 | 21.17% |
| **Mùa thu (`autumn`)** | 1.220 | **Baseline 2: + Vệ tinh** | **7.5905** | **5.4364** | **0.7980** | **20.88%** |
| **Mùa đông (`winter`)** | 2.550 | Baseline 1: OpenAQ + Khí tượng | 12.6696 | 8.5453 | 0.8284 | 21.13% |
| **Mùa đông (`winter`)** | 2.550 | **Baseline 2: + Vệ tinh** | **12.3754** | **8.3545** | **0.8363** | **19.97%** |

### 2.3. Kiểm định Thống kê Giả thuyết H5 (Wilcoxon Signed-Rank Test)
- Xét hiệu sai số tuyệt đối từng cặp mẫu out-of-fold $\Delta |e_i| = |y_i - \hat{y}_{i,\text{B1}}| - |y_i - \hat{y}_{i,\text{B2}}|$ trên $N = 7.290$ mẫu:
  - MAE trung bình giảm từ **$6,736\ \mu\text{g/m}^3$** xuống **$6,580\ \mu\text{g/m}^3$** (RMSE giảm từ $10,193$ xuống **$9,935\ \mu\text{g/m}^3$**).
  - Kiểm định một phía **Wilcoxon Signed-Rank Test** cho kết quả **$p\text{-value} = 1,63 \times 10^{-4} \ll 0,01$**.
- **Kết luận H5:** **Bác bỏ $H_0$, chấp nhận giả thuyết H5.** Mô hình **Baseline 2 (OpenAQ + Khí tượng + Vệ tinh)** học tốt hơn và dự báo chính xác hơn **Baseline 1**.

---

## 3. Kiểm định Giả thuyết H6: Suy rộng Không gian sang Các Ô Không có Trạm (Spatial GroupCV)

> **Phát biểu H6:** Khi suy rộng sang các ô lưới hoàn toàn chưa từng có trạm quan trắc trong tập huấn luyện (`GroupKFold` theo `grid_id`), dữ liệu vệ tinh độ phân giải cao (1 km) giúp **Baseline 2** giảm mạnh sai số so với **Baseline 1**.

### 3.1. Kết quả Đánh giá Chéo Không gian (`Spatial_GroupCV` theo `grid_id`)

| Chế độ đánh giá | Mô hình | Số mẫu ($N$) | RMSE ($\mu\text{g/m}^3$) $\downarrow$ | MAE ($\mu\text{g/m}^3$) $\downarrow$ | $R^2$ $\uparrow$ | MAPE (%) $\downarrow$ |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Spatial GroupCV** | **Baseline 1: OpenAQ + Khí tượng** | 7.290 | 17.0115 | 11.8387 | 0.5332 | 37.26% |
| **Spatial GroupCV** | **Baseline 2: OpenAQ + Khí tượng + Vệ tinh** | 7.290 | **15.8949** | **10.9720** | **0.5925** | **34.48%** |

### 3.2. Kiểm định Thống kê & Giải thích Vật lý cho Giả thuyết H6
- Khi giấu hoàn toàn chuỗi thời gian của các ô lưới kiểm thử (`Spatial_GroupCV`):
  - **Baseline 1** chỉ dựa vào ERA5-Land ($\sim 9\text{ km}$) và ERA5 BLH ($\sim 25\text{ km}$) nên khó phân biệt được sự khác nhau giữa các ô lưới 1 km lân cận ($R^2 = 0,5332$).
  - **Baseline 2** nhờ có thêm **MODIS MAIAC AOD ($1\text{ km}$)**, **VIIRS Nighttime Lights ($1\text{ km}$)** và **Sentinel-5P ($\text{NO}_2, \text{O}_3, \text{CO}$)** đã giảm sai số RMSE tới **$-1,117\ \mu\text{g/m}^3$**, giảm MAE **$-0,867\ \mu\text{g/m}^3$**, giảm MAPE **$-2,78\%$** và nâng $R^2$ thêm **$+5,93$ điểm phần trăm** (từ $0,5332$ lên **$0,5925$**).
  - Kiểm định cặp **Wilcoxon Signed-Rank Test** trên tập dự báo không gian cho kết quả **$p\text{-value} = 1,86 \times 10^{-59} \ll 0,01$**.
- **Kết luận H6:** **Bác bỏ $H_0$, chấp nhận giả thuyết H6.** Dữ liệu vệ tinh đóng vai trò quyết định khi ước tính $\text{PM}_{2.5}$ cho 99% diện tích các ô lưới không có trạm tại Hà Nội.

---

## 4. Phân tích Độ quan trọng Đặc trưng (Top 15 Feature Importance của Baseline 2)

Bảng xếp hạng mức độ đóng góp (Gain Importance trung bình qua 5 folds) từ [`data/marts/model_feature_importance.parquet`](../data/marts/model_feature_importance.parquet):

| Hạng | Tên đặc trưng (`feature`) | Nhóm dữ liệu | Tỷ trọng (`importance`) | Ý nghĩa Vật lý / Môi trường |
| :---: | :--- | :--- | :---: | :--- |
| 1 | `precip_mm` | Khí tượng (ERA5-Land) | **14.77%** | Hiệu ứng rửa trôi ướt (khớp với giả thuyết **H2**). |
| 2 | `blh_min_m` | Khí tượng (ERA5 BLH) | **12.12%** | Độ cao lớp biên cực tiểu ban đêm/sáng sớm — bẫy nghịch nhiệt (khớp với **H1**). |
| 3 | `day_of_year` | Lịch (`dim_date`) | **6.03%** | Chu kỳ mùa trong năm (khớp với giả thuyết **H3**). |
| 4 | **`o3_mol_m2`** | **Vệ tinh (Sentinel-5P)** | **5.67%** | Cột Ozone khí quyển — chỉ dấu bức xạ quang hóa và trạng thái khí quyển. |
| 5 | `easting_m` | Không gian (`dim_grid_1km`) | **5.52%** | Gradient không gian Đông – Tây (từ vùng đồi núi phía Tây sang lõi đô thị phía Đông). |
| 6 | `temp_2m_c` | Khí tượng (ERA5-Land) | **5.40%** | Nhiệt độ không khí ở độ cao 2 m. |
| 7 | `dewpoint_2m_c` | Khí tượng (ERA5-Land) | **5.13%** | Nhiệt độ điểm sương (độ ẩm tuyệt đối của khối khí). |
| 8 | `blh_mean_m` | Khí tượng (ERA5 BLH) | **4.67%** | Độ cao lớp biên trung bình ngày. |
| 9 | `month` | Lịch (`dim_date`) | **4.34%** | Tháng trong năm. |
| 10 | **`aod_047`** | **Vệ tinh (MODIS MAIAC 1km)** | **3.93%** | Độ dày quang học sol khí bước sóng $0,47\ \mu\text{m}$ (khớp với **H4**). |
| 11 | `northing_m` | Không gian (`dim_grid_1km`) | **3.83%** | Gradient không gian Bắc – Nam. |
| 12 | `rh_pct` | Khí tượng (ERA5-Land) | **3.11%** | Độ ẩm tương đối (ảnh hưởng sự phát triển kích thước hạt hút ẩm). |
| 13 | `surface_pressure_hpa` | Khí tượng (ERA5-Land) | **2.86%** | Áp suất khí quyển bề mặt (liên quan lưỡi cao áp lạnh mùa Đông). |
| 14 | `year` | Lịch (`dim_date`) | **2.65%** | Xu hướng biến động liên năm (2021–2026). |
| 15 | **`viirs_radiance`** | **Vệ tinh (VIIRS DNB 1km)** | **2.53%** | Cường độ ánh sáng ban đêm 1 km — phân biệt mật độ đô thị/khu công nghiệp giữa các ô lưới. |

---

## 5. Báo cáo Ước tính trên Tập 7.577.390 Ô-Ngày (`pred_grid_daily_pm25.parquet`)

Toàn bộ **7.577.390 dòng** (`3.610 ô × 2.099 ngày`, từ `01/01/2021` đến `30/09/2026`) trong [`mart_grid_daily_features.parquet`](../data/marts/mart_grid_daily_features.parquet) đã được ước tính và lưu tại [`data/marts/pred_grid_daily_pm25.parquet`](../data/marts/pred_grid_daily_pm25.parquet).

### 5.1. Thống kê Toàn cục trên 7.577.390 Ô-Ngày

| Mô hình ước tính | Tên cột trong `pred_grid_daily_pm25.parquet` | Số dòng | Trung bình ($\mu\text{g/m}^3$) | Độ lệch chuẩn ($\mu\text{g/m}^3$) | Nhỏ nhất ($\mu\text{g/m}^3$) | Lớn nhất ($\mu\text{g/m}^3$) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline 1 (OpenAQ + Khí tượng)** | `pm25_pred_b1_meteo` | 7.577.390 | 34.17 | 20.47 | 0.00 | 221.64 |
| **Baseline 2 (OpenAQ + Khí tượng + Vệ tinh)** | `pm25_pred_b2_meteo_sat` | 7.577.390 | **34.14** | **20.52** | 0.00 | **227.28** |

### 5.2. Tổng hợp Ước tính PM2.5 Toàn Lưới Hà Nội theo Từng Năm (2021–2026)

| Năm | Số ô-ngày (`grid_days`) | TB Baseline 1 ($\mu\text{g/m}^3$) | TB Baseline 2 ($\mu\text{g/m}^3$) | Trung vị Baseline 2 ($\mu\text{g/m}^3$) | Phân vị 95% Baseline 2 ($\mu\text{g/m}^3$) | Tỷ lệ ô-ngày vượt QCVN $> 50\ \mu\text{g/m}^3$ (%) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021** | 1.317.650 | 34.45 | 34.86 | 27.20 | 83.82 | 20.90% |
| **2022** | 1.317.650 | 33.58 | 33.49 | 29.00 | 70.92 | 16.26% |
| **2023** | 1.317.650 | 36.16 | 36.31 | 31.53 | 77.79 | 20.27% |
| **2024** | 1.321.260 | 32.10 | 32.32 | 29.23 | 66.00 | 14.13% |
| **2025** | 1.317.650 | 34.88 | 34.49 | 27.67 | 80.19 | 19.57% |
| **2026** *(đến 30/09)* | 985.530 | 33.75 | 33.14 | 28.64 | 74.57 | 14.67% |

---

## 6. Cách Tái tạo Kết quả (Reproducibility)

Chạy lệnh CLI duy nhất từ thư mục gốc của dự án:

```powershell
# Chạy lại trọn bộ pipeline dữ liệu (dims -> staging -> facts -> marts)
python run.py build

# Huấn luyện, đánh giá chéo 2 Baseline và xuất file ước tính 7,57 triệu dòng
python run.py train
```
