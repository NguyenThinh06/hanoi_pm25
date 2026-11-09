<#
.SYNOPSIS
    Script khởi động toàn bộ hệ thống PM2.5 Hà Nội bằng 1-chạm (Docker Compose).
.DESCRIPTION
    Tự động:
    1. Kiểm tra Docker Desktop đã bật hay chưa.
    2. Chuẩn bị file cấu hình .env.
    3. Giải nén gói bàn giao Parquet nếu chưa có.
    4. Khởi động 3 dịch vụ: Database PostGIS, API FastAPI, Frontend React.
    5. Tự động nạp dữ liệu vào Database bằng container importer.
    6. Tự động mở trình duyệt truy cập Dashboard http://localhost.
.EXAMPLE
    .\run.ps1
#>

[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$FullData
)

$ErrorActionPreference = "Stop"

if ($FullData) {
    $env:IMPORT_SMOKE_MONTH = "all"
    Write-Host "  [Cấu hình] Chế độ nạp toàn bộ 15.15 triệu bản ghi 5 năm." -ForegroundColor Cyan
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "     PM2.5 HÀ NỘI — KHỞI ĐỘNG TOÀN BỘ HỆ THỐNG 1-CHẠM (DOCKER COMPOSE)          " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Kiểm tra Docker Engine
Write-Host "`n[1/5] Kiểm tra Docker Engine..." -ForegroundColor Yellow
try {
    $dockerCheck = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "LỖI: Docker Desktop chưa được bật!" -ForegroundColor Red
        Write-Host "Vui lòng mở ứng dụng Docker Desktop trên máy và đợi biểu tượng cá voi chuyển sang màu xanh, sau đó chạy lại script này." -ForegroundColor White
        exit 1
    }
} catch {
    Write-Host "LỖI: Không tìm thấy lệnh docker. Vui lòng cài đặt Docker Desktop." -ForegroundColor Red
    exit 1
}
Write-Host "  -> Docker Engine đang hoạt động tốt." -ForegroundColor Green

# 2. Chuẩn bị file .env
Write-Host "`n[2/5] Kiểm tra file cấu hình .env..." -ForegroundColor Yellow
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "  -> Đã tự động tạo file .env từ .env.example." -ForegroundColor Green
} else {
    Write-Host "  -> File .env đã tồn tại." -ForegroundColor Green
}

# 3. Kiểm tra gói dữ liệu bàn giao
Write-Host "`n[3/5] Kiểm tra gói dữ liệu bàn giao (Parquet & Geometry)..." -ForegroundColor Yellow
if (-not (Test-Path "HANDOVER_MANIFEST.json")) {
    $bundleTar = "handover_bundles/pm25-handover-2026-11-04.tar.gz"
    if (Test-Path $bundleTar) {
        Write-Host "  -> Đang tự động giải nén gói dữ liệu bàn giao ($bundleTar)..." -ForegroundColor White
        tar -xzf $bundleTar
        Write-Host "  -> Giải nén hoàn tất." -ForegroundColor Green
    } else {
        Write-Host "  [Cảnh báo] Không tìm thấy file $bundleTar. Hệ thống sẽ sử dụng dữ liệu có sẵn trong outputs/." -ForegroundColor Yellow
    }
} else {
    Write-Host "  -> Dữ liệu bàn giao đã sẵn sàng." -ForegroundColor Green
}

# 4. Khởi động Docker Compose
Write-Host "`n[4/5] Khởi động cụm dịch vụ Docker (PostGIS, Importer, FastAPI, Nginx)..." -ForegroundColor Yellow
if ($Build) {
    Write-Host "  -> Đang build lại các container (--build)..." -ForegroundColor White
    docker compose up -d --build
} else {
    Write-Host "  -> Khởi động container (sử dụng cache hiện có)..." -ForegroundColor White
    docker compose up -d
}

Write-Host "`n[5/5] Đang chờ hệ thống nạp dữ liệu và sẵn sàng phục vụ..." -ForegroundColor Yellow
$timeout = 180
$elapsed = 0
$ready = $false

while ($elapsed -lt $timeout) {
    Start-Sleep -Seconds 3
    $elapsed += 3
    try {
        $res = Invoke-RestMethod -Uri "http://localhost/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($res.status -eq "ok" -and $res.database -eq "ready") {
            $ready = $true
            break
        }
    } catch {
        # Đang chờ container khởi động
         = 
    }
    Write-Host -NoNewline "."
}

Write-Host ""
if ($ready) {
    Write-Host "`n================================================================================" -ForegroundColor Green
    Write-Host "           HỆ THỐNG PM2.5 HÀ NỘI ĐÃ SẴN SÀNG HOẠT ĐỘNG!                        " -ForegroundColor Green
    Write-Host "================================================================================" -ForegroundColor Green
    Write-Host "  🌐 Giao diện Dashboard : http://localhost" -ForegroundColor Cyan
    Write-Host "  📚 Tài liệu API Swagger: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  💚 Kiểm tra sức khỏe   : http://localhost/health" -ForegroundColor Cyan
    Write-Host "================================================================================"

    # Tự động mở trình duyệt
    Start-Process "http://localhost"
} else {
    Write-Host "`n[Lưu ý] Các container đang trong quá trình nạp dữ liệu. Bạn có thể kiểm tra log bằng lệnh:" -ForegroundColor Yellow
    Write-Host "docker compose logs -f" -ForegroundColor White
}
