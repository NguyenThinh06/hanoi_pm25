# Business Case & Khung Giả thuyết Nghiên cứu — Ước tính PM2.5 Lưới 1 km Hà Nội (2021–2026)

---

## 1. Bối cảnh Nghiệp vụ & Bài toán (Problem Statement)

### 1.1. Khoảng trống dữ liệu quan trắc mặt đất
Trên toàn bộ diện tích tự nhiên của thành phố Hà Nội ($\approx 3.359\text{ km}^2$), hệ thống lưới chuẩn của dự án chia thành **3.610 ô lưới $1\text{ km} \times 1\text{ km}$** (hệ quy chiếu phẳng `EPSG:3405`). Tuy nhiên, qua rà soát toàn bộ dữ liệu cảm biến mặt đất **OpenAQ v3** từ **01/01/2021 đến 30/09/2026** (2.099 ngày):
- Trong lần chạy được báo cáo, tập huấn luyện có **7.290 dòng trạm-ngày hợp lệ** trên **36 / 3.610 ô lưới**; mart có 9.207 dòng trạm-ngày có nhãn. Đây là số lượng theo bộ dữ liệu và bộ lọc đã sử dụng, không khẳng định tổng số trạm thực tế trên địa bàn.
- Tỷ lệ 36 / 3.610 là tỷ lệ **số ô** có nhãn hợp lệ trong tập này, không phải tỷ lệ diện tích hay dân số được quan trắc. Các ô còn lại không có nhãn trạm hợp lệ trong tập huấn luyện, không nhất thiết không có bất kỳ trạm hoặc quan trắc nào.

### 1.2. Hệ lụy đối với Sức khỏe Cộng đồng & Quản lý Môi trường
Tại các trạm có quan trắc hợp lệ ở Hà Nội giai đoạn 2021–2026:
- Nồng độ $\text{PM}_{2.5}$ trung bình đạt **$37,68\ \mu\text{g/m}^3$** (trung vị **$31,17\ \mu\text{g/m}^3$**, cực đại lên tới **$231,04\ \mu\text{g/m}^3$**).
- Có tới **87,58% số ngày-trạm vượt khuyến nghị an toàn 24 giờ của WHO ($15\ \mu\text{g/m}^3$)** và **22,25% số ngày-trạm vượt Quy chuẩn Quốc gia QCVN 05:2023/BTNMT ($50\ \mu\text{g/m}^3$)**.

Khi dữ liệu trạm trong tập nghiên cứu chỉ bao phủ một phần nhỏ số ô, việc sau đây gặp hạn chế:
1. Đánh giá mức độ phơi nhiễm bụi mịn $\text{PM}_{2.5}$ dài hạn và ngắn hạn cho người dân ở các quận/huyện ngoại thành, khu công nghiệp và hành lang giao thông.
2. Phân biệt đâu là ô nhiễm nền do điều kiện khí tượng bất lợi (nghịch nhiệt, lặng gió) và đâu là điểm nóng phát thải cục bộ (đô thị hóa, giao thông, đốt phụ phẩm nông nghiệp).

---

## 2. Mục tiêu Giải pháp Khoa học Dữ liệu (Objectives)

Xây dựng pipeline đa nguồn và mô hình **XGBoost** để **ước tính hồi cứu nồng độ PM2.5 trung bình ngày** cho các ô lưới có đặc trưng đầu vào. Tối đa theo cấu hình là 3.610 ô × 2.099 ngày = 7.577.390 ô-ngày; dữ liệu khí tượng và vệ tinh có thể bị thiếu. Đây chưa phải hệ thống dự báo ngày tiếp theo:
1. **Lịch & Không gian (`dim_date`, `dim_grid_1km`):** `year`, `month`, `day_of_week`, `day_of_year`, `is_weekend`, `easting_m`, `northing_m`.
2. **Khí tượng tái phân tích (`ERA5-Land` & `ERA5 BLH`):** Nhiệt độ (`temp_2m_c`), điểm sương (`dewpoint_2m_c`), độ ẩm (`rh_pct`), lượng mưa (`precip_mm`), vận tốc/hướng/độ bền gió (`wind_speed_10m_ms`, `wind_u_10m_ms`, `wind_v_10m_ms`, `wind_persistence`, `wind_dir_10m_deg`), áp suất bề mặt (`surface_pressure_hpa`), và độ cao lớp biên (`blh_mean_m`, `blh_min_m`).
3. **Viễn thám Vệ tinh (`Sentinel-5P`, `MODIS MAIAC AOD`, `VIIRS DNB`):** Cột $\text{NO}_2$ tầng đối lưu (`no2_trop_mol_m2`), cột $\text{CO}$ (`co_mol_m2`), cột $\text{O}_3$ (`o3_mol_m2`), cột $\text{SO}_2$ (`so2_mol_m2`), độ dày quang học sol khí 1 km (`aod_047`), và bức xạ ánh sáng ban đêm 1 km (`viirs_radiance`).

---

## 3. Hệ thống Giả thuyết Nghiên cứu cần Kiểm định (Hypotheses Framework)

Các giả thuyết dưới đây nghiên cứu **mối liên hệ**, không tự chứng minh quan hệ nhân quả. Các mẫu trạm–ngày có thể phụ thuộc theo thời gian và không gian; kết quả kiểm định cần được diễn giải cùng giả định độc lập và phương pháp chia tập. KFold ngẫu nhiên không đánh giá khả năng dự đoán tương lai.

Để đảm bảo tính chặt chẽ khoa học, dự án chia các giả thuyết thành **2 nhóm rõ rệt**:
- **Nhóm A (H1 – H4):** Các giả thuyết về cơ chế vật lý, khí tượng và tín hiệu vệ tinh — được **kiểm định bằng EDA & Thống kê suy diễn** trong [`notebooks/02_hypothesis_testing_eda.ipynb`](../notebooks/02_hypothesis_testing_eda.ipynb) (sau khi đã thực hiện EDA dữ liệu thô và chốt quyết định thiết kế tại [`notebooks/01_raw_and_initial_eda.ipynb`](../notebooks/01_raw_and_initial_eda.ipynb)).
- **Nhóm B (H5 – H6):** Các giả thuyết về khả năng học và suy rộng không gian của mô hình — được **kiểm định bằng thực nghiệm mô hình XGBoost** và báo cáo tại [`docs/model_report.md`](./model_report.md).

### 3.1. Nhóm A — Giả thuyết Kiểm định bằng EDA & Thống kê (`notebooks/02_hypothesis_testing_eda.ipynb`)

| Mã | Tên giả thuyết | Phát biểu giả thuyết ($H_1$) | Cơ chế vật lý / môi trường | Phép kiểm định thống kê |
| :--- | :--- | :--- | :--- | :--- |
| **H1** | **Hiệu ứng Bẫy nghịch nhiệt (Boundary Layer Height)** | Những ngày có độ cao lớp biên cực tiểu thấp (`blh_min_m < 100 m`) có nồng độ $\text{PM}_{2.5}$ cao hơn có ý nghĩa thống kê so với ngày lớp biên cao (`blh_min_m > 300 m`). | Khi `blh_min_m` thấp vào ban đêm và sáng sớm, lớp nghịch nhiệt đóng vai trò như "nắp vung" khóa chặt bụi mịn sát mặt đất, ngăn cản khuếch tán thẳng đứng. | Tương quan Spearman $\rho$ & Kiểm định một phía Mann-Whitney U ($\alpha = 0.01$). |
| **H2** | **Hiệu ứng Rửa trôi ướt (Wet Scavenging)** | Những ngày có mưa vừa đến mưa to (`precip_mm >= 5 mm`) có nồng độ $\text{PM}_{2.5}$ thấp hơn có ý nghĩa thống kê so với những ngày khô ráo (`precip_mm < 1 mm`). | Quá trình lắng đọng ướt (Wet Deposition): hạt mưa va chạm và cuốn các hạt sol khí lơ lửng rơi xuống mặt đất. | Kiểm định Mann-Whitney U & Welch's t-test ($\alpha = 0.01$). |
| **H3** | **Chu kỳ Gió mùa (Seasonality)** | Nồng độ $\text{PM}_{2.5}$ và tần suất vượt ngưỡng QCVN ($> 50\ \mu\text{g/m}^3$) có sự phân hóa có ý nghĩa thống kê giữa 4 mùa, cao nhất vào mùa Đông – Xuân và thấp nhất vào mùa Hạ. | Mùa Đông chịu ảnh hưởng của gió mùa Đông Bắc lạnh, khô, nghịch nhiệt bức xạ và vận chuyển ô nhiễm liên vùng; mùa Hạ đối lưu nhiệt mạnh và mưa rào thường xuyên. | Kiểm định phi tham số Kruskal-Wallis qua 4 mùa ($\alpha = 0.01$). |
| **H4** | **Tín hiệu Viễn thám Vệ tinh (Satellite Signal)** | Dù bị khuyết dữ liệu do mây che phủ, các biến vệ tinh (`aod_047`, `no2_trop_mol_m2`, `co_mol_m2`, `o3_mol_m2`, `viirs_radiance`) vẫn có tương quan có ý nghĩa thống kê với $\text{PM}_{2.5}$ mặt đất. | `aod_047` phản ánh trực tiếp mật độ hạt sol khí trong cột khí quyển; `no2_trop_mol_m2`, `co_mol_m2` và `viirs_radiance` đại diện cho cường độ giao thông, đốt cháy nhiên liệu và mức độ đô thị hóa tại từng ô 1 km. | Tương quan Pearson $r$, Spearman $\rho$ & đánh giá tỷ lệ bao phủ (coverage) thực tế. |

---

### 3.2. Nhóm B — Giả thuyết Kiểm định bằng Mô hình Học máy XGBoost (`docs/model_report.md`)

| Mã | Tên giả thuyết | Phát biểu giả thuyết ($H_1$) | Thiết kế thực nghiệm Mô hình | Tiêu chuẩn đánh giá & Kiểm định |
| :--- | :--- | :--- | :--- | :--- |
| **H5** | **Giá trị gia tăng của Vệ tinh trong Khả năng Học & Dự báo (5-Fold CV)** | Mô hình **Baseline 2 (`XGBoost: OpenAQ + Khí tượng + Vệ tinh`)** đạt sai số dự báo (RMSE, MAE, MAPE) thấp hơn và $R^2$ cao hơn có ý nghĩa thống kê so với **Baseline 1 (`XGBoost: OpenAQ + Khí tượng`)** trên cả tập huấn luyện và kiểm thử chéo 5-Fold CV. | Huấn luyện cùng cấu hình siêu tham số `XGBRegressor` trên `7.290` dòng chuẩn (`is_valid_day = 1`), so sánh `Baseline 1` (27 đặc trưng Lịch + Tọa độ + Khí tượng) với `Baseline 2` (34 đặc trưng = Baseline 1 + 7 biến Vệ tinh). | So sánh RMSE, MAE, $R^2$, MAPE toàn cục và theo 4 mùa; Kiểm định cặp **Wilcoxon Signed-Rank Test** trên hiệu sai số tuyệt đối $\Delta \|e\| = \|e_{\text{B1}}\| - \|e_{\text{B2}}\|$ ($\alpha = 0.01$). |
| **H6** | **Khả năng Suy rộng Không gian sang Ô Không có Trạm (Spatial GroupCV & 7,57 triệu ô-ngày)** | Khi dự báo cho các ô lưới hoàn toàn bị giấu trạm trong quá trình huấn luyện (**Spatial GroupKFold theo `grid_id`**), **Baseline 2** giảm đáng kể sai số so với **Baseline 1** và tái tạo hợp lý trường phân bố $\text{PM}_{2.5}$ trên tập **7.577.390 ô-ngày**. | Chia 5-Fold bằng `GroupKFold(n_splits=5)` theo `grid_id` (toàn bộ chuỗi thời gian của một ô trạm chỉ nằm ở Train hoặc Val), sau đó dùng mô hình huấn luyện toàn cục ước tính trên `mart_grid_daily_features.parquet` (7,57M dòng). | So sánh RMSE, MAE, $R^2$ trên `Spatial_GroupCV`; Kiểm định cặp **Wilcoxon Signed-Rank Test** trên sai số suy rộng không gian; Kiểm tra tính hợp lý vật lý trên 7.577.390 dòng dự báo. |

---

## 4. Liên kết Tài liệu trong Dự án

1. **Đặc tả Kiến trúc Lakehouse & Schema:** [`docs/schema.md`](./schema.md)
2. **Notebook 01 — EDA Ban đầu trên Dữ liệu Thô & Ra Quyết định:** [`notebooks/01_raw_and_initial_eda.ipynb`](../notebooks/01_raw_and_initial_eda.ipynb)
3. **Notebook 02 — EDA & Kiểm định Giả thuyết H1 – H4:** [`notebooks/02_hypothesis_testing_eda.ipynb`](../notebooks/02_hypothesis_testing_eda.ipynb)
4. **Báo cáo Kiểm định Mô hình (H5 – H6) & Ước tính 7,57M ô-ngày:** [`docs/model_report.md`](./model_report.md)
5. **Mã nguồn Huấn luyện & Ước tính Lưới:** [`src/models/train_baselines.py`](../src/models/train_baselines.py)
6. **Các bước phát triển end-to-end:** [`docs/roadmap.md`](./roadmap.md)
