#!/usr/bin/env bash
# ==============================================================================
# Script khởi động toàn bộ hệ thống PM2.5 Hà Nội bằng 1-chạm (Docker Compose)
# ==============================================================================
set -euo pipefail

echo "================================================================================"
echo "     PM2.5 HÀ NỘI — KHỞI ĐỘNG TOÀN BỘ HỆ THỐNG 1-CHẠM (DOCKER COMPOSE)          "
echo "================================================================================"

# 1. Kiểm tra Docker
echo -e "\n[1/5] Kiểm tra Docker Engine..."
if ! docker info >/dev/null 2>&1; then
    echo "LỖI: Docker chưa được bật hoặc người dùng không có quyền chạy docker." >&2
    exit 1
fi
echo "  -> Docker Engine đang hoạt động tốt."

# 2. File .env
echo -e "\n[2/5] Kiểm tra file cấu hình .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  -> Đã tự động tạo file .env từ .env.example."
else
    echo "  -> File .env đã tồn tại."
fi

# 3. Gói dữ liệu
echo -e "\n[3/5] Kiểm tra gói dữ liệu bàn giao (Parquet & Geometry)..."
if [ ! -f "HANDOVER_MANIFEST.json" ]; then
    if [ -f "handover_bundles/pm25-handover-2026-11-04.tar.gz" ]; then
        echo "  -> Đang giải nén gói dữ liệu..."
        tar -xzf "handover_bundles/pm25-handover-2026-11-04.tar.gz"
        echo "  -> Giải nén hoàn tất."
    fi
fi

# 4. Khởi động Docker Compose
echo -e "\n[4/5] Khởi động cụm dịch vụ Docker (PostGIS, Importer, FastAPI, Nginx)..."
if [ "${1:-}" = "--build" ]; then
    echo "  -> Đang build lại các container (--build)..."
    docker compose up -d --build
else
    echo "  -> Khởi động container (sử dụng cache hiện có)..."
    docker compose up -d
fi

# 5. Chờ hệ thống sẵn sàng
echo -e "\n[5/5] Đang chờ hệ thống nạp dữ liệu và sẵn sàng phục vụ..."
timeout=180
elapsed=0
ready=0

while [ $elapsed -lt $timeout ]; do
    sleep 3
    elapsed=$((elapsed + 3))
    if curl -s -f http://localhost/health >/dev/null 2>&1; then
        ready=1
        break
    fi
    printf "."
done

echo ""
if [ $ready -eq 1 ]; then
    echo "================================================================================"
    echo "           HỆ THỐNG PM2.5 HÀ NỘI ĐÃ SẴN SÀNG HOẠT ĐỘNG!                        "
    echo "================================================================================"
    echo "  🌐 Giao diện Dashboard : http://localhost"
    echo "  📚 Tài liệu API Swagger: http://localhost:8000/docs"
    echo "  💚 Kiểm tra sức khỏe   : http://localhost/health"
    echo "================================================================================"
else
    echo "Container đang nạp dữ liệu. Bạn có thể xem log bằng: docker compose logs -f"
fi
