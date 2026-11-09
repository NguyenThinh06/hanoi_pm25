# Frontend Dashboard (Gói 3)

React + Vite + Tailwind + Leaflet, gọi 6 endpoint dữ liệu của Hợp đồng API v1 (`docs/HANDOVER.md` mục 5).

## Cấu trúc thư mục

```text
frontend/
├── index.html            # Trang gốc của Vite
├── vite.config.js        # Plugin React/Tailwind, proxy /api sang backend
├── mock-api.mjs          # API giả theo Hợp đồng v1, dùng khi dev không có backend
├── package.json          # Dependency và các lệnh npm
├── package-lock.json     # Khóa phiên bản dependency
└── src/
    ├── main.jsx          # Điểm vào React, nạp CSS
    ├── index.css         # Tailwind và style nền bản đồ
    ├── App.jsx           # Bố cục, bộ chọn model/ngày, chú giải, panel ô
    ├── MapView.jsx       # Bản đồ Leaflet: lưới 1 km và lớp trạm
    ├── HistoryChart.jsx  # Biểu đồ SVG lịch sử ô và bảng số liệu
    ├── api.js            # Gọi API, xử lý lỗi, hook useGet
    ├── lib.js            # Thang màu µg/m³, định dạng số, xử lý ngày
    └── lib.test.js       # Unit test cho lib.js
```

## Chạy local

```powershell
npm install
npm run mock   # API giả ở cổng 8000, số liệu giả lập, chỉ dùng khi chưa có Gói 2
npm run dev    # terminal khác, mở http://localhost:5173
```

Khi đã có FastAPI ở địa chỉ khác cổng 8000:

```powershell
$env:API_URL = "http://localhost:9000"; npm run dev
```

## Build và kiểm thử

```powershell
npm test        # thang màu, xử lý ngày, cửa sổ lịch sử
npm run build   # xuất ra dist/
```

## Ghi chú tích hợp (Gói 4)

- `dist/` là web tĩnh, gọi `/api/...` cùng origin. Nginx cần proxy `/api` sang service `api`.
- Panel ô hiển thị "Giá trị API" chưa làm tròn và bảng số liệu lịch sử, dùng cho đối soát 3 điểm.
- Nền bản đồ dùng tile công cộng OpenStreetMap nên trình duyệt cần có Internet.
