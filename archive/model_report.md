# Báo cáo Đánh giá và Huấn luyện Mô hình Ước tính Hồi cứu $\text{PM}_{2.5}$ Hà Nội

> **Phiên bản báo cáo**: `v2.0.0-retrospective` — Chuẩn hóa quy trình đánh giá theo 3 phương pháp (`Spatial GroupKFold`, `Random KFold`, `Temporal split`) và huấn luyện hai mô hình cuối cùng trên toàn bộ dữ liệu hợp lệ (`2021-01-01` đến `2026-09-30`).

---

## 1. Bài toán và tập dữ liệu

### 1.1. Mục tiêu bài toán
Dự án giải quyết bài toán **ước tính hồi cứu (retrospective estimation) nồng độ $\text{PM}_{2.5}$ trung bình ngày ($\mu\text{g/m}^3$) trên lưới không gian $1\text{ km} \times 1\text{ km}$ toàn thành phố Hà Nội** (`3.610` ô lưới chuẩn CRS `EPSG:3405`), đặc biệt tại **các ô lưới không có trạm quan trắc mặt đất** (`3.580/3.610` ô, chiếm `99,17%` diện tích lưới). Đây là bài toán nội suy/ngoại suy không gian – thời gian hồi cứu sử dụng đồng thời khí tượng tái phân tích cùng ngày và vệ tinh cùng ngày, **không phải** bài toán dự báo ngày mai (operational forecasting).

### 1.2. Nguồn dữ liệu và quy mô tập huấn luyện
- **Bảng dữ liệu nguồn**: [`data/marts/mart_station_daily_training.parquet`](../data/marts/mart_station_daily_training.parquet) (`20.478` dòng trạm–ngày trước lọc).
- **Khóa định danh dòng**: `(station_id, date_id)` — kiểm định `0` dòng trùng khóa.
- **Điều kiện lọc hợp lệ**: `is_valid_day = 1` (trạm có $\ge 18/24$ giờ quan trắc hợp lệ trong ngày) và `pm25_mean IS NOT NULL`.
- **Thống kê tập dữ liệu hợp lệ sau lọc**:
  - **Số dòng hợp lệ ($N$)**: `7.290` dòng (toàn bộ `7.290` dòng đều có `pm25_mean > 0`, giá trị nhỏ nhất `2,04` $\mu\text{g/m}^3$).
  - **Số trạm quan trắc (`station_id`)**: `32` trạm OpenAQ.
  - **Số ô lưới có trạm (`grid_id`)**: `30` ô lưới $1\text{ km} \times 1\text{ km}$ (`2` ô lưới có 2 trạm đặt cùng ô: `grid_581000_2327000` và `grid_588000_2326000`).
  - **Khoảng thời gian thực tế**: `2021-01-01` đến `2026-09-30` (`1.801` ngày riêng biệt).
  - **Tỷ lệ khuyết ảnh vệ tinh quang học (`aod_047_missing = 1`)**: `6.320 / 7.290` dòng (`86,69%`); số dòng có AOD hợp lệ (`aod_047_missing = 0`): `970` dòng (`13,31%`).

---

## 2. Hai baseline và cấu hình kỹ thuật

### 2.1. Danh sách đặc trưng (Features)
Hai mô hình sử dụng cùng tập dữ liệu, cùng phép chia và cùng cấu hình thuật toán, chỉ khác nhau ở nhóm biến vệ tinh để đánh giá giá trị gia tăng của dữ liệu viễn thám:

| Mô hình | Mã định danh | Số biến | Nhóm đặc trưng đầu vào |
| :--- | :--- | :---: | :--- |
| **Baseline 1** | `Baseline_1_OpenAQ_Meteo` | `27` | **Lịch & chu kỳ (8)**: `year`, `month`, `day_of_year`, `day_of_week`, `is_weekend`, `season`, `doy_sin`, `doy_cos`<br>**Tọa độ không gian (2)**: `lat`, `lon`<br>**Khí tượng ERA5-Land + GFS (17)**: `t2m_mean`, `t2m_min`, `t2m_max`, `d2m_mean`, `rh_mean`, `u10_mean`, `v10_mean`, `wind_speed_mean`, `wind_dir_sin`, `wind_dir_cos`, `sp_mean`, `tp_sum`, `blh_mean`, `blh_min`, `blh_max`, `ssrd_sum`, `ventilation_index` |
| **Baseline 2** | `Baseline_2_OpenAQ_Meteo_Sat` | `34` | Toàn bộ `27` biến của **Baseline 1** + **7 biến vệ tinh MODIS MAIAC & Sentinel-5P TROPOMI**: `aod_047`, `aod_055`, `aod_047_missing`, `no2_trop_col`, `no2_missing`, `co_col`, `co_missing` |

> **Lưu ý về mối liên hệ thống kê**: Mức độ đóng góp đặc trưng trong mô hình cây quyết định chỉ phản ánh mối liên hệ thống kê dự báo (predictive association) trên tập dữ liệu hiện có, **không** được diễn giải như quan hệ nhân quả vật lý – hóa học khí quyển.

### 2.2. Cấu hình XGBoost, xử lý dữ liệu và định nghĩa Metric
- **Cấu hình `XGBRegressor` cố định** (giữ nguyên giữa hai baseline, không tinh chỉnh siêu tham số):
  - `n_estimators = 300`, `max_depth = 6`, `learning_rate = 0.05`, `subsample = 0.8`, `colsample_bytree = 0.8`, `min_child_weight = 5`, `reg_alpha = 0.1`, `reg_lambda = 1.0`, `n_jobs = 4`, `random_state = 42` (`seed = 42`).
- **Xử lý giá trị thiếu (Missing values)**: Giữ nguyên `NaN` cho các biến vệ tinh (`aod_047`, `aod_055`, `no2_trop_col`, `co_col`) kết hợp cờ báo thiếu nhị phân (`aod_047_missing`, `no2_missing`, `co_missing`) để thuật toán phân nhánh原生 (native missing-value routing) của XGBoost xử lý trực tiếp.
- **Hậu xử lý dự đoán**: Cắt ngưỡng dưới về `0.0` ($\hat{y} = \max(0, \hat{y}_{\text{raw}})$) nhằm đảm bảo nồng độ $\text{PM}_{2.5}$ không âm.
- **Định nghĩa các thước đo sai số**:
  - $\text{MAE}$ ($\mu\text{g/m}^3$), $\text{RMSE}$ ($\mu\text{g/m}^3$) và $R^2$ tính theo `scikit-learn`.
  - $\text{MAPE}$ (`%`) chỉ tính trên các dòng có `pm25_mean > 0` (kèm báo cáo `n_mape_samples`).
  - **Macro-MAE theo ô lưới** ($\mu\text{g/m}^3$): Tính $\text{MAE}_g$ riêng cho từng `grid_id` $g \in \{1, \dots, G\}$ rồi lấy trung bình cộng không trọng số $\frac{1}{G}\sum_{g=1}^G \text{MAE}_g$, giúp mỗi ô lưới có trọng số ngang nhau bất kể số ngày quan trắc dày hay mỏng. Không lấy trung bình cộng $\text{RMSE}$ từng ô để gọi là $\text{RMSE}$ gộp.
  - Quy ước dấu độ lệch giữa hai mô hình: $\Delta\text{Metric} = \text{Metric}(\text{Baseline 2}) - \text{Metric}(\text{Baseline 1})$. Với $\text{MAE}$, $\text{RMSE}$, $\text{MAPE}$: $\Delta < 0$ nghĩa là **Baseline 2 tốt hơn**; với $R^2$: $\Delta > 0$ nghĩa là **Baseline 2 tốt hơn**.

---

## 3. Bảng ba phương pháp đánh giá

| Phương pháp | Câu hỏi trả lời | Cách chia dữ liệu | Vai trò trong dự án |
| :--- | :--- | :--- | :--- |
| **A. Spatial GroupKFold**<br>(`spatial_groupkfold`) | Mô hình ước tính chính xác đến đâu tại **các ô lưới $1\text{ km}$ hoàn toàn chưa có nhãn $\text{PM}_{2.5}$ trong tập huấn luyện**? | `GroupKFold(n_splits=5)` nhóm theo `grid_id` trên toàn bộ `7.290` dòng hợp lệ (`30` ô lưới chia đều 5 fold, mỗi fold giữ lại `6` ô lưới làm validation; $\text{train\_grids} \cap \text{val\_grids} = \varnothing$). | **Đánh giá chính (Primary Evaluation)** — phản ánh trực tiếp mục tiêu lập bản đồ hồi cứu trên `3.580` ô lưới không có trạm. |
| **B. Random KFold**<br>(`random_kfold`) | Sai số nội suy khi mô hình được phép thấy cả **cùng trạm, cùng ô lưới và các ngày lân cận** trong tập huấn luyện là bao nhiêu? | `KFold(n_splits=5, shuffle=True, random_state=42)` chia ngẫu nhiên theo dòng trên toàn bộ `7.290` dòng hợp lệ (cùng `grid_id` và `station_id` xuất hiện ở cả train lẫn validation). | **Mốc tham chiếu (Reference Benchmark)** — minh họa mức độ lạc quan khi chia ngẫu nhiên theo dòng; **không** dùng làm bằng chứng ngoại suy không gian. |
| **C. Temporal Split**<br>(`temporal_split`) | Mô hình huấn luyện trên giai đoạn lịch sử (`2021–2025`) hoạt động ra sao khi áp dụng sang **giai đoạn thời gian mới (`2026`)** tại các trạm đã biết? | Huấn luyện trên `date < 2026-01-01` (`6.280` dòng, `32` trạm, `30` ô); đánh giá trên `2026-01-01 <= date <= 2026-09-30` (`1.010` dòng, `6` trạm, `6` ô; $\max(\text{train\_date}) < \min(\text{val\_date})$). | **Đánh giá bổ sung theo thời gian (Supplementary Evaluation)** — kiểm tra độ bền vững khi dịch chuyển năm và hiệu quả của AOD trong mùa thiếu ảnh 2026. |

---

## 4. Kết quả thực nghiệm

### 4.1. Tổng hợp so sánh hai Baseline trên ba phương pháp đánh giá

| Phương pháp đánh giá | Tập đánh giá ($N$ dòng / $N_{\text{MAPE}}$) | Mô hình | MAE ($\mu\text{g/m}^3$) | RMSE ($\mu\text{g/m}^3$) | $R^2$ | MAPE (%) | Macro-MAE theo Grid ($\mu\text{g/m}^3$) | Kết luận phương pháp |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **A. Spatial GroupKFold**<br>*(Đánh giá chính)* | OOF toàn tập<br>(`7.290 / 7.290`, `30` grids) | **Baseline 1**<br>**Baseline 2**<br>$\Delta (\text{B2} - \text{B1})$ | `11,5955`<br>**`11,0451`**<br>`-0,5504` | `16,7911`<br>**`15,9541`**<br>`-0,8370` | `0,5452`<br>**`0,5894`**<br>`+0,0442` | `36,18%`<br>**`34,92%`**<br>`-1,26%` | `11,1494`<br>**`10,6515`**<br>`-0,4979` | **Baseline 2 thắng**<br>(thắng gộp, Macro-MAE, `4/5` fold, `17/30` grid) |
| **B. Random KFold**<br>*(Tham chiếu)* | OOF toàn tập<br>(`7.290 / 7.290`, `30` grids) | **Baseline 1**<br>**Baseline 2**<br>$\Delta (\text{B2} - \text{B1})$ | `6,7710`<br>**`6,6247`**<br>`-0,1463` | `10,2885`<br>**`10,0164`**<br>`-0,2721` | `0,8293`<br>**`0,8382`**<br>`+0,0089` | `22,24%`<br>**`21,51%`**<br>`-0,73%` | `6,7862`<br>**`6,5996`**<br>`-0,1866` | **Baseline 2 thắng**<br>(thắng `5/5` fold, `19/30` grid) |
| **C. Temporal Split**<br>*(Bổ sung `2026`)* | Validation `2026`<br>(`1.010 / 1.010`, `6` trạm) | **Baseline 1**<br>**Baseline 2**<br>$\Delta (\text{B2} - \text{B1})$ | `11,1443`<br>**`11,0847`**<br>`-0,0596` | `16,2301`<br>**`15,9539`**<br>`-0,2762` | `0,5770`<br>**`0,5913`**<br>`+0,0143` | **`28,08%`**<br>`28,89%`<br>`+0,81%` | `11,0592`<br>`11,2321`<br>`+0,1729` | **Baseline 2 thắng nhẹ gộp** ($\Delta\text{MAE} = -0,06$), thắng rõ khi có AOD (`-2,37`) |

---

### 4.2. Chi tiết Phương pháp A: Spatial GroupKFold (Đánh giá chính)

#### a) Kết quả theo từng Fold (`5` folds, mỗi fold `6` ô lưới độc lập)

| Fold | Số dòng ($N$) | Số trạm | Số ô lưới | Số ngày | Khoảng ngày | B1 MAE | B2 MAE | $\Delta\text{MAE}$ | B1 RMSE | B2 RMSE | $\Delta\text{RMSE}$ | B1 $R^2$ | B2 $R^2$ | Model tốt hơn |
| :---: | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Fold 0** | `1.547` | `6` | `6` | `961` | `2024-01-30` → `2026-09-30` | `8,9505` | **`7,5420`** | `-1,4085` | `13,8051` | **`11,2033`** | `-2,6018` | `0,6029` | **`0,7385`** | **Baseline 2** |
| **Fold 1** | `1.552` | `6` | `6` | `957` | `2024-01-30` → `2026-09-30` | `8,9407` | **`8,4936`** | `-0,4471` | `12,1863` | **`11,4888`** | `-0,6975` | `0,7159` | **`0,7475`** | **Baseline 2** |
| **Fold 2** | `1.564` | `7` | `6` | `968` | `2024-01-30` → `2026-09-30` | **`12,8692`** | `13,4423` | `+0,5731` | **`17,5101`** | `18,4526` | `+0,9425` | **`0,4734`** | `0,4152` | **Baseline 1** |
| **Fold 3** | `1.318` | `6` | `6` | `876` | `2024-01-30` → `2026-09-30` | `12,9293` | **`12,5920`** | `-0,3373` | `19,1139` | **`18,7540`** | `-0,3599` | `0,5187` | **`0,5367`** | **Baseline 2** |
| **Fold 4** | `1.309` | `7` | `6` | `855` | `2021-01-01` → `2025-02-04` | `14,9922` | **`13,7854`** | `-1,2068` | `21,2917` | **`19,4329`** | `-1,8588` | `0,4327` | **`0,5275`** | **Baseline 2** |

#### b) Kết quả theo trạng thái có/thiếu AOD trong Spatial GroupKFold

| Nhóm dữ liệu | Cờ `aod_047_missing` | Số dòng ($N$) | Số trạm / ô / ngày | B1 MAE | B2 MAE | $\Delta\text{MAE}$ | B1 RMSE | B2 RMSE | $\Delta\text{RMSE}$ | B1 $R^2$ | B2 $R^2$ | Model tốt hơn |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Có AOD (`aod_available`)** | `0` | `970` (`13,3%`) | `30` / `29` / `237` | `16,1252` | **`15,1786`** | `-0,9466` | `22,6531` | **`21,2084`** | `-1,4447` | `0,4196` | **`0,4913`** | **Baseline 2** |
| **Thiếu AOD (`aod_missing`)** | `1` | `6.320` (`86,7%`) | `32` / `30` / `1.666` | `10,9003` | **`10,4107`** | `-0,4896` | `15,6989` | **`14,9854`** | `-0,7135` | `0,5273` | **`0,5693`** | **Baseline 2** |

#### c) Tóm tắt theo `30` ô lưới (`grid_id`) trong Spatial GroupKFold
- **Tỷ lệ thắng theo ô lưới**:
  - Theo $\text{MAE}$: **Baseline 2 thắng `17/30` ô (`56,7%`)**, Baseline 1 thắng `13/30` ô (`43,3%`), `0` ô hòa.
  - Theo cả $\text{MAE}$ lẫn $\text{RMSE}$ đồng thuận: **Baseline 2 thắng tuyệt đối tại `16/30` ô**, Baseline 1 thắng tại `12/30` ô, `2/30` ô bất đồng giữa $\text{MAE}$ và $\text{RMSE}$ (`grid_576000_2327000` và `grid_573000_2313000`).
- **Tương quan với quy mô mẫu**: Trong nhóm `16` ô lưới có $\ge 200$ ngày quan trắc (chiếm `6.245 / 7.290` dòng, tức `85,7%` tổng dữ liệu), Baseline 2 thắng ở các trạm dài hạn trọng điểm như `US Diplomatic Post: Hanoi` (`grid_583000_2325000`, $N=667$, $\Delta\text{MAE} = -1,7241$ $\mu\text{g/m}^3$), `An Khánh` (`grid_574000_2322000`, $N=619$, $\Delta\text{MAE} = -3,6545$ $\mu\text{g/m}^3$), `ĐHBK cổng Parabol` (`grid_587000_2323000`, $N=432$, $\Delta\text{MAE} = -1,4229$ $\mu\text{g/m}^3$), và `Liên Quan` (`grid_559000_2328000`, $N=276$, $\Delta\text{MAE} = -3,4892$ $\mu\text{g/m}^3$). Ngược lại, Baseline 1 tốt hơn tại cụm trạm `556 Nguyễn Văn Cừ` ($N=647$, $\Delta\text{MAE} = +1,4587$) và `Công viên Nhân Chính` ($N=503$, $\Delta\text{MAE} = +1,0690$).

<details>
<summary><b>Bảng chi tiết 30 ô lưới trong Spatial GroupKFold (sắp xếp theo số mẫu giảm dần)</b></summary>

| `grid_id` | Fold | Trạm đại diện (`station_names`) | $N$ | Khoảng ngày | B1 MAE | B2 MAE | $\Delta\text{MAE}$ | B1 RMSE | B2 RMSE | $\Delta\text{RMSE}$ | Model tốt hơn (MAE) |
| :--- | :---: | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `grid_583000_2325000` | 4 | US Diplomatic Post: Hanoi | `667` | `2021-01-01` → `2025-02-04` | `15,8265` | **`14,1024`** | `-1,7241` | `22,5201` | **`20,4666`** | `-2,0535` | **Baseline 2** |
| `grid_591000_2328000` | 2 | 556 Nguyễn Văn Cừ | `647` | `2024-01-30` → `2026-09-30` | **`12,8606`** | `14,3193` | `+1,4587` | **`17,1255`** | `19,1799` | `+2,0544` | **Baseline 1** |
| `grid_574000_2322000` | 0 | An Khánh | `619` | `2024-02-26` → `2026-09-30` | `11,7695` | **`8,1150`** | `-3,6545` | `17,8417` | **`12,6065`** | `-5,2352` | **Baseline 2** |
| `grid_581000_2327000` | 1 | ĐH Quốc Gia; Cục Viễn thông | `562` | `2024-02-26` → `2026-09-30` | `8,2749` | **`7,8422`** | `-0,4327` | `11,3341` | **`10,7292`** | `-0,6049` | **Baseline 2** |
| `grid_583000_2322000` | 2 | Công viên Nhân Chính | `503` | `2024-01-30` → `2026-09-30` | **`15,7282`** | `16,7972` | `+1,0690` | **`20,6537`** | `21,7634` | `+1,1097` | **Baseline 1** |
| `grid_585000_2328000` | 3 | Quảng Bá | `468` | `2024-02-26` → `2026-09-29` | `9,2248` | **`8,7113`** | `-0,5135` | `13,1282` | **`12,5919`** | `-0,5363` | **Baseline 2** |
| `grid_587000_2323000` | 3 | ĐHBK cổng Parabol Giải Phóng | `432` | `2024-01-30` → `2025-11-28` | `9,3753` | **`7,9524`** | `-1,4229` | `12,8692` | **`11,2647`** | `-1,6045` | **Baseline 2** |
| `grid_584000_2323000` | 0 | Láng Hạ | `399` | `2024-01-30` → `2025-07-07` | **`7,1608`** | `7,4489` | `+0,2881` | `10,1277` | **`9,9694`** | `-0,1583` | **Baseline 1** |
| `grid_586000_2324000` | 1 | Công viên Thống Nhất | `358` | `2024-02-26` → `2025-07-07` | **`11,9320`** | `12,0686` | `+0,1366` | **`15,4314`** | `15,4424` | `+0,0110` | **Baseline 1** |
| `grid_585000_2324000` | 0 | Hồ Đắc Di - Đống Đa | `284` | `2024-02-26` → `2025-02-04` | `6,3862` | **`6,3075`** | `-0,0787` | **`8,8040`** | `8,9988` | `+0,1948` | **Baseline 2** |
| `grid_599000_2321000` | 1 | Đa Tốn | `283` | `2024-02-26` → `2025-02-03` | **`7,0720`** | `7,8274` | `+0,7554` | **`8,7001`** | `9,7672` | `+1,0671` | **Baseline 1** |
| `grid_559000_2328000` | 4 | Liên Quan | `276` | `2024-02-03` → `2025-01-14` | `19,6130` | **`16,1238`** | `-3,4892` | `24,9957` | **`20,0039`** | `-4,9918` | **Baseline 2** |
| `grid_588000_2316000` | 1 | Pháp Vân | `271` | `2024-01-30` → `2025-02-04` | `6,8497` | **`5,1576`** | `-1,6921` | `9,9827` | **`7,7773`** | `-2,2054` | **Baseline 2** |
| `grid_588000_2326000` | 2 | Đào Duy Từ; Đông Kinh Nghĩa Thục | `267` | `2024-02-26` → `2025-06-09` | **`9,7604`** | `9,9032` | `+0,1428` | **`11,8960`** | `12,2051` | `+0,3091` | **Baseline 1** |
| `grid_576000_2327000` | 3 | Minh Khai - Bắc Từ Liêm | `214` | `2024-01-30` → `2026-08-04` | **`24,0831`** | `24,4866` | `+0,4035` | `32,9184` | **`32,8955`** | `-0,0229` | **Baseline 1** |
| `grid_581000_2298000` | 4 | Quảng Phú Cầu | `211` | `2024-02-26` → `2024-12-07` | **`5,0116`** | `5,2474` | `+0,2358` | **`5,8324`** | `6,0807` | `+0,2483` | **Baseline 1** |
| `grid_580000_2292000` | 0 | Vân Đình | `157` | `2024-02-26` → `2025-02-03` | **`8,2489`** | `8,7811` | `+0,5322` | **`10,8248`** | `11,4630` | `+0,6382` | **Baseline 1** |
| `grid_588000_2325000` | 1 | Cung thiếu nhi | `129` | `2024-02-26` → `2025-02-04` | **`8,2678`** | `11,1514` | `+2,8836` | **`9,5657`** | `12,9973` | `+3,4316` | **Baseline 1** |
| `grid_578000_2347000` | 3 | Thanh Xuân - Sóc Sơn | `124` | `2024-02-26` → `2024-09-09` | `24,1268` | **`22,8542`** | `-1,2726` | `29,0742` | **`27,5667`** | `-1,5075` | **Baseline 2** |
| `grid_579000_2306000` | 4 | Kim Bài | `121` | `2024-02-26` → `2024-12-08` | **`8,5757`** | `8,6976` | `+0,1219` | **`11,5435`** | `11,9157` | `+0,3722` | **Baseline 1** |
| `grid_573000_2313000` | 2 | Chúc Sơn | `118` | `2024-10-04` → `2025-02-04` | `6,0135` | **`5,8808`** | `-0,1327` | **`7,2665`** | `7,4301` | `+0,1636` | **Baseline 2** |
| `grid_587000_2326000` | 1 | Hàng Đậu | `109` | `2024-02-26` → `2024-11-26` | `12,0515` | **`9,4323`** | `-2,6192` | `13,6067` | **`12,4995`** | `-1,1072` | **Baseline 2** |
| `grid_584000_2321000` | 0 | Khương Trung | `88` | `2024-02-26` → `2024-12-11` | `6,7700` | **`6,7244`** | `-0,0456` | `8,6060` | **`8,3291`** | `-0,2769` | **Baseline 2** |
| `grid_579000_2326000` | 3 | Cầu Diễn | `60` | `2024-09-17` → `2024-12-11` | `9,2685` | **`7,7699`** | `-1,4986` | `12,9817` | **`11,2853`** | `-1,6964` | **Baseline 2** |
| `grid_585000_2283000` | 4 | Đội Bình | `34` | `2024-02-26` → `2024-05-05` | **`8,3937`** | `10,5847` | `+2,1910` | **`9,4086`** | `11,7272` | `+2,3186` | **Baseline 1** |
| `grid_581000_2319000` | 2 | Văn Quán | `16` | `2024-02-26` → `2024-04-02` | **`4,5441`** | `6,6304` | `+2,0863` | **`6,6513`** | `8,4544` | `+1,8031` | **Baseline 1** |
| `grid_582000_2328000` | 3 | Tây Hồ Tây | `11` | `2024-02-26` → `2024-03-19` | `9,6102` | **`7,6540`** | `-1,9562` | `11,3136` | **`9,0319`** | `-2,2817` | **Baseline 2** |
| `grid_586000_2329000` | 2 | Tứ Liên | `11` | `2024-02-26` → `2024-03-19` | `17,8950` | **`11,5608`** | `-6,3342` | `21,9363` | **`13,3616`** | `-8,5747` | **Baseline 2** |
| `grid_586000_2323000` | 4 | Kim Liên | `4` | `2024-02-28` → `2024-03-05` | **`9,2621`** | `14,5417` | `+5,2796` | **`11,2527`** | `16,5721` | `+5,3194` | **Baseline 1** |
| `grid_588000_2321000` | 4 | Tân Mai | `4` | `2024-02-26` → `2024-02-29` | `11,1544` | **`8,0501`** | `-3,1043` | `12,3676` | **`9,1611`** | `-3,2065` | **Baseline 2** |

</details>

---

### 4.3. Chi tiết Phương pháp B: Random KFold (Mốc tham chiếu)

Khi chia ngẫu nhiên theo dòng (`KFold(n_splits=5, shuffle=True, random_state=42)`), cùng một `grid_id`, `station_id` và các ngày kế cận xuất hiện đồng thời trong tập train và validation:
- **Sai số giảm mạnh một cách giả tạo so với Spatial GroupKFold**:
  - **Baseline 1**: $\text{MAE}$ giảm từ `11,5955` xuống `6,7710` $\mu\text{g/m}^3$ (`-41,6%`), $R^2$ tăng từ `0,5452` lên `0,8293`.
  - **Baseline 2**: $\text{MAE}$ giảm từ `11,0451` xuống `6,6247` $\mu\text{g/m}^3$ (`-40,0%`), $R^2$ tăng từ `0,5894` lên `0,8382`.
- **So sánh giữa hai baseline trong Random KFold**: Baseline 2 thắng trên cả **5/5 fold** ($\Delta\text{MAE}$ từng fold từ `-0,0404` đến `-0,2619` $\mu\text{g/m}^3$) và thắng trên **19/30 ô lưới (`63,3%`)**, với Macro-MAE đạt `6,5996` so với `6,7862` $\mu\text{g/m}^3$ của Baseline 1.

---

### 4.4. Chi tiết Phương pháp C: Temporal Split (Đánh giá bổ sung theo thời gian)

- **Phép chia**:
  - **Tập Train (`date < 2026-01-01`)**: `6.280` dòng, `32` trạm, `30` ô lưới, `1.528` ngày (`2021-01-01` → `2025-12-31`).
  - **Tập Validation (`date >= 2026-01-01`)**: `1.010` dòng, `6` trạm, `6` ô lưới, `273` ngày (`2026-01-01` → `2026-09-30`).
  - **Độ chồng lấp trạm**: Toàn bộ `6/6` trạm trong tập validation năm 2026 (`100%` số dòng) đều đã xuất hiện trong tập train trước 2026; nhóm `unseen_in_train` rỗng (`0` dòng, metric lưu `null` với `null_reason = "empty_group"`).

#### a) Kết quả theo nhóm có/thiếu AOD trên tập Validation 2026

| Nhóm dữ liệu | Cờ `aod_047_missing` | Số dòng ($N$) | Số trạm / ô / ngày | B1 MAE | B2 MAE | $\Delta\text{MAE}$ | B1 RMSE | B2 RMSE | $\Delta\text{RMSE}$ | B1 $R^2$ | B2 $R^2$ | B1 MAPE | B2 MAPE | Model tốt hơn |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Toàn bộ Validation 2026** | `0 & 1` | `1.010` (`100%`) | `6` / `6` / `273` | `11,1443` | **`11,0847`** | `-0,0596` | `16,2301` | **`15,9539`** | `-0,2762` | `0,5770` | **`0,5913`** | **`28,08%`** | `28,89%` | **Baseline 2** (MAE/RMSE/$R^2$) |
| **Có AOD (`aod_available`)** | `0` | `74` (`7,3%`) | `4` / `4` / `30` | `19,5302` | **`17,1562`** | `-2,3740` | `25,2832` | **`22,2929`** | `-2,9903` | `0,4576` | **`0,5783`** | `27,70%` | **`26,74%`** | **Baseline 2 thắng rõ** |
| **Thiếu AOD (`aod_missing`)** | `1` | `936` (`92,7%`) | `6` / `6` / `260` | **`10,4814`** | `10,6047` | `+0,1233` | **`15,2873`** | `15,3414` | `+0,0541` | **`0,5388`** | `0,5355` | **`28,10%`** | `29,06%` | **Baseline 1 nhỉnh nhẹ** |

#### b) Kết quả theo từng trạm (`6` trạm) trên tập Validation 2026

| `station_id` | Tên trạm | `grid_id` | $N$ | Khoảng ngày `2026` | B1 MAE | B2 MAE | $\Delta\text{MAE}$ | B1 RMSE | B2 RMSE | $\Delta\text{RMSE}$ | B1 $R^2$ | B2 $R^2$ | Model tốt hơn |
| :--- | :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `openaq_2161290` | 556 Nguyễn Văn Cừ | `grid_591000_2328000` | `265` | `2026-01-01` → `2026-09-30` | **`10,9466`** | `11,2260` | `+0,2794` | `15,3754` | **`15,2448`** | `-0,1306` | `0,5741` | **`0,5813`** | Bất đồng nhẹ (B1 MAE / B2 RMSE) |
| `openaq_2161292` | Công viên Nhân Chính | `grid_583000_2322000` | `264` | `2026-01-01` → `2026-09-30` | `12,1862` | **`11,4520`** | `-0,7342` | `17,8533` | **`16,7473`** | `-1,1060` | `0,5966` | **`0,6451`** | **Baseline 2** |
| `openaq_2161295` | ĐH Quốc Gia | `grid_581000_2327000` | `206` | `2026-01-01` → `2026-09-30` | **`9,4653`** | `9,5934` | `+0,1281` | **`13,4405`** | `13,8642` | `+0,4237` | **`0,4733`** | `0,4395` | **Baseline 1** |
| `openaq_2161300` | An Khánh | `grid_574000_2322000` | `191` | `2026-01-01` → `2026-09-30` | `9,2896` | **`8,7357`** | `-0,5539` | `12,3506` | **`11,8307`** | `-0,5199` | `0,6736` | **`0,7005`** | **Baseline 2** |
| `openaq_2161311` | Quảng Bá | `grid_585000_2328000` | `78` | `2026-02-04` → `2026-09-29` | **`16,2508`** | `17,3260` | `+1,0752` | **`25,6720`** | `26,2074` | `+0,5354` | **`0,4710`** | `0,4487` | **Baseline 1** |
| `openaq_2161306` | Minh Khai - Bắc Từ Liêm | `grid_576000_2327000` | `6` | `2026-06-14` → `2026-08-04` | **`8,1767`** | `9,0593` | `+0,8826` | **`8,4943`** | `9,2251` | `+0,7308` | `-0,2317` | `-0,4527` | **Baseline 1** ($N=6$ rất nhỏ) |

---

## 5. Kết luận và lý giải

1. **Vì sao `Spatial GroupKFold` là phương pháp đánh giá chính?**
   - Mục tiêu cốt lõi của dự án là ước tính nồng độ $\text{PM}_{2.5}$ hồi cứu trên toàn bộ lưới `3.610` ô $1\text{ km} \times 1\text{ km}$ của Hà Nội, trong đó `99,17%` số ô lưới không có trạm quan trắc mặt đất.
   - `Spatial GroupKFold` theo `grid_id` buộc mô hình phải dự đoán cho các ô lưới hoàn toàn bị giấu khỏi tập huấn luyện ($\text{train\_grids} \cap \text{val\_grids} = \varnothing$), mô phỏng đúng bản chất bài toán ngoại suy không gian sang ô lưới không trạm trong cùng giai đoạn lịch sử.
2. **Vai trò bổ sung của `Random KFold` và `Temporal Split`**:
   - `Random KFold` ($\text{MAE} \approx 6,62\text{--}6,77$ $\mu\text{g/m}^3$, $R^2 \approx 0,83\text{--}0,84$) cho thấy khi mô hình được phép nhìn thấy cùng vị trí trạm và các ngày liền kề, sai số giảm hơn `40%` so với ngoại suy không gian ($\text{MAE} \approx 11,05\text{--}11,60$ $\mu\text{g/m}^3$). Sự chênh lệch này chứng minh nếu chỉ báo cáo Random KFold sẽ đánh giá quá lạc quan năng lực lập bản đồ ở ô không có trạm.
   - `Temporal Split` kiểm tra khả năng tổng quát hóa sang năm `2026` khi mô hình chỉ được học dữ liệu `2021–2025` tại các trạm đã biết.
3. **So sánh hai Baseline và nhận xét thận trọng**:
   - Trên phương pháp đánh giá chính **`Spatial GroupKFold`** (toàn bộ `7.290` dòng), **Baseline 2 (`OpenAQ + Meteo + Satellite`) vượt trội nhất quán so với Baseline 1** trên cả metric gộp ($\Delta\text{MAE} = -0,5504$ $\mu\text{g/m}^3$, $\Delta\text{RMSE} = -0,8370$ $\mu\text{g/m}^3$, $\Delta R^2 = +0,0442$), Macro-MAE theo ô lưới (`10,6515` so với `11,1494` $\mu\text{g/m}^3$, $\Delta = -0,4979$), số fold thắng (`4/5` fold), số ô lưới thắng (`17/30` ô), và thắng ở cả hai phân nhóm có AOD (`-0,9466` $\mu\text{g/m}^3$) lẫn thiếu AOD (`-0,4896` $\mu\text{g/m}^3$, nhờ thông tin khí cột `no2_trop_col` và `co_col` từ Sentinel-5P TROPOMI).
   - Trên **`Random KFold`**, **Baseline 2** cũng thắng toàn diện (`5/5` fold, `19/30` grid).
   - Trên **`Temporal Split` (`2026`)**, **Baseline 2** có $\text{MAE}$ và $\text{RMSE}$ gộp thấp hơn nhẹ ($\Delta\text{MAE} = -0,0596$, $\Delta\text{RMSE} = -0,2762$ $\mu\text{g/m}^3$) và vượt trội rõ rệt trong những ngày quang mây có AOD (`aod_available`, $N=74$, $\Delta\text{MAE} = -2,3740$ $\mu\text{g/m}^3$). Tuy nhiên, trong những ngày mất ảnh quang học (`aod_missing`, chiếm `92,7%` mẫu năm 2026) và ở chỉ số $\text{MAPE}$, Baseline 1 nhỉnh hơn nhẹ ($\Delta\text{MAE} = +0,1233$ $\mu\text{g/m}^3$). Do đó, dù Baseline 2 là mô hình chính tốt hơn cho bài toán lập bản đồ hồi cứu, cả hai mô hình cuối cùng (`baseline1` và `baseline2`) đều được huấn luyện trên `100%` dữ liệu hợp lệ và lưu trữ đầy đủ để phục vụ đối chiếu.

---

## 6. Giới hạn kỹ thuật và dữ liệu

1. **Tự tương quan không gian giữa các ô lưới lân cận (Spatial autocorrelation)**: `GroupKFold` theo `grid_id` đảm bảo không trùng ô lưới giữa train và validation, nhưng chưa áp dụng khoảng đệm loại trừ không gian (spatial buffer zone). Các trạm nội đô Hà Nội cách nhau $1\text{--}3\text{ km}$ vẫn nằm ở các fold khác nhau, nên sai số tại vùng ngoại thành xa trạm (như Sóc Sơn, Liên Quan — nơi $\text{MAE}$ lên tới `16–24` $\mu\text{g/m}^3$) cao hơn đáng kể so với trung tâm.
2. **Độ phủ trạm quan trắc thưa và mất cân bằng thời gian**: Chỉ có `30 / 3.610` ô lưới (`0,83%`) có trạm quan trắc. Giai đoạn `2021–2023` chỉ có duy nhất 1 trạm (`US Diplomatic Post: Hanoi`); mạng lưới 31 trạm cảm biến mới bắt đầu hoạt động từ năm `2024`.
3. **Tỷ lệ khuyết dữ liệu AOD quang học rất cao (`86,69%`)**: Do mây che phủ đặc trưng của khí hậu miền Bắc Việt Nam (đặc biệt mùa xuân – nồm ẩm), `6.320 / 7.290` dòng bị thiếu `aod_047`. Ở tập validation `2026`, tỷ lệ thiếu AOD lên tới `92,67%` (`936 / 1.010` dòng).
4. **Độ trễ công bố dữ liệu (Temporal data release availability)**: Đây là hệ thống ước tính hồi cứu phụ thuộc vào lịch phát hành dữ liệu tái phân tích ERA5-Land và sản phẩm vệ tinh MODIS/TROPOMI chuẩn hóa; không thể chạy suy luận thời gian thực nếu các nguồn vệ tinh/tái phân tích của ngày mục tiêu chưa được công bố.
5. **Tập dữ liệu năm 2026 đã từng được khảo sát trước (Prior exploration)**: Phân bố đầu vào và nhãn `pm25_mean` của giai đoạn `2026-01-01` → `2026-09-30` đã được khảo sát trong quá trình phân tích khám phá dữ liệu (`docs/eda_temporal_split.md`) và các vòng đánh giá trước đó. Vì vậy, kết quả `Temporal Split` năm 2026 là phép kiểm tra bổ sung theo thời gian, không phải một tập test mù hoàn toàn nguyên vẹn (untouched blind holdout).

---

## 7. Lệnh tái tạo và danh mục Artifact đã lưu

### 7.1. Lệnh CLI tái tạo kết quả
```bash
# 1. Chạy toàn bộ 3 phương pháp đánh giá (Spatial GroupKFold, Random KFold, Temporal Split)
python run.py evaluate

# Hoặc chạy riêng từng phương pháp đánh giá:
python run.py evaluate --method spatial_groupkfold
python run.py evaluate --method random_kfold
python run.py evaluate --method temporal_split

# 2. Huấn luyện 2 mô hình cuối cùng (Baseline 1 & Baseline 2) trên 100% dữ liệu hợp lệ (N=7.290)
python run.py train-final

# 3. Chạy trọn gói cả đánh giá 3 phương pháp lẫn huấn luyện mô hình cuối cùng
python run.py train

# 4. Kiểm tra chất lượng mã nguồn (Ruff) và chạy bộ kiểm thử tự động (Pytest)
python run.py lint
python run.py test
```

### 7.2. Danh sách Artifact đánh giá và Mô hình đã lưu (`outputs/`)
- **Kết quả đánh giá 3 phương pháp (`outputs/evaluation/`)**:
  - `Spatial GroupKFold` (Đánh giá chính):
    - [`outputs/evaluation/spatial_groupkfold/metrics.json`](../outputs/evaluation/spatial_groupkfold/metrics.json)
    - [`outputs/evaluation/spatial_groupkfold/predictions.parquet`](../outputs/evaluation/spatial_groupkfold/predictions.parquet) (`7.290` dòng OOF)
    - [`outputs/evaluation/spatial_groupkfold/fold_assignments.parquet`](../outputs/evaluation/spatial_groupkfold/fold_assignments.parquet)
    - [`outputs/evaluation/spatial_groupkfold/config.yaml`](../outputs/evaluation/spatial_groupkfold/config.yaml) & [`metadata.json`](../outputs/evaluation/spatial_groupkfold/metadata.json)
  - `Random KFold` (Mốc tham chiếu):
    - [`outputs/evaluation/random_kfold/metrics.json`](../outputs/evaluation/random_kfold/metrics.json)
    - [`outputs/evaluation/random_kfold/predictions.parquet`](../outputs/evaluation/random_kfold/predictions.parquet) (`7.290` dòng OOF)
    - [`outputs/evaluation/random_kfold/fold_assignments.parquet`](../outputs/evaluation/random_kfold/fold_assignments.parquet)
    - [`outputs/evaluation/random_kfold/config.yaml`](../outputs/evaluation/random_kfold/config.yaml) & [`metadata.json`](../outputs/evaluation/random_kfold/metadata.json)
  - `Temporal Split` (Đánh giá bổ sung `train < 2026-01-01`, `val >= 2026-01-01`):
    - [`outputs/evaluation/temporal_split/metrics.json`](../outputs/evaluation/temporal_split/metrics.json)
    - [`outputs/evaluation/temporal_split/predictions.parquet`](../outputs/evaluation/temporal_split/predictions.parquet) (`1.010` dòng validation)
    - [`outputs/evaluation/temporal_split/split_assignments.parquet`](../outputs/evaluation/temporal_split/split_assignments.parquet) (`7.290` dòng gán nhãn `train`/`validation`)
    - [`outputs/evaluation/temporal_split/config.yaml`](../outputs/evaluation/temporal_split/config.yaml) & [`metadata.json`](../outputs/evaluation/temporal_split/metadata.json)
- **Hai mô hình cuối cùng huấn luyện trên `100%` dữ liệu hợp lệ (`outputs/models/`, định dạng chuẩn XGBoost JSON)**:
  - **Baseline 1 (`Baseline_1_OpenAQ_Meteo`, `27` biến, $N = 7.290$)**:
    - [`outputs/models/baseline1/model.json`](../outputs/models/baseline1/model.json)
    - [`outputs/models/baseline1/metadata.json`](../outputs/models/baseline1/metadata.json) & [`config.yaml`](../outputs/models/baseline1/config.yaml)
    - [`outputs/models/baseline1/sample_verification_predictions.parquet`](../outputs/models/baseline1/sample_verification_predictions.parquet) (kiểm chứng nạp lại mô hình trên `25` dòng mẫu: sai lệch tuyệt đối lớn nhất `0,0`)
  - **Baseline 2 (`Baseline_2_OpenAQ_Meteo_Sat`, `34` biến, $N = 7.290$)**:
    - [`outputs/models/baseline2/model.json`](../outputs/models/baseline2/model.json)
    - [`outputs/models/baseline2/metadata.json`](../outputs/models/baseline2/metadata.json) & [`config.yaml`](../outputs/models/baseline2/config.yaml)
    - [`outputs/models/baseline2/sample_verification_predictions.parquet`](../outputs/models/baseline2/sample_verification_predictions.parquet) (kiểm chứng nạp lại mô hình trên `25` dòng mẫu: sai lệch tuyệt đối lớn nhất `0,0`)
- **Sổ đăng ký thực nghiệm cục bộ (`outputs/registry/`)**:
  - Bản ghi JSON cục bộ: [`outputs/registry/evaluation_runs.json`](../outputs/registry/evaluation_runs.json), [`fold_metrics.json`](../outputs/registry/fold_metrics.json), [`model_registry.json`](../outputs/registry/model_registry.json), [`artifact_registry.json`](../outputs/registry/artifact_registry.json) và [`registry_status.json`](../outputs/registry/registry_status.json).
  - Metadata lưu bằng JSON cục bộ; PostgreSQL và migration thuộc giai đoạn triển khai tiếp theo.
- **Lưu trữ lịch sử (Archive)**: Các script và file kết quả trung gian của các vòng thử nghiệm cũ đã được chuyển sang [`archive/2026-11-03_legacy_evaluations/`](../archive/README.md).
