<#
.SYNOPSIS
    Script sao lưu và phục hồi cơ sở dữ liệu PostgreSQL PM2.5 Hà Nội qua Docker (Gói 4).
.EXAMPLE
    .\scripts\backup_restore.ps1 -Action backup
    .\scripts\backup_restore.ps1 -Action restore -BackupFile "backups/hanoi_pm25_latest.dump"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backup", "restore")]
    [string]$Action,

    [Parameter(Mandatory = $false)]
    [string]$BackupFile = "backups/hanoi_pm25_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump",

    [Parameter(Mandatory = $false)]
    [string]$ContainerName = "hanoi_pm25_db",

    [Parameter(Mandatory = $false)]
    [string]$DbUser = "hanoi_pm25",

    [Parameter(Mandatory = $false)]
    [string]$DbName = "hanoi_pm25"
)

$ErrorActionPreference = "Stop"

if ($Action -eq "backup") {
    $backupDir = Split-Path $BackupFile -Parent
    if ($backupDir -and -not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }

    Write-Host "================================================================================" -ForegroundColor Cyan
    Write-Host "BẮT ĐẦU SAO LƯU DATABASE (pg_dump) QUA DOCKER CONTAINER: $ContainerName" -ForegroundColor Cyan
    Write-Host "  + File đích: $BackupFile" -ForegroundColor Cyan
    Write-Host "================================================================================"

    # Chạy pg_dump định dạng custom (-Fc) nén tối ưu
    docker exec -t $ContainerName pg_dump -U $DbUser -d $DbName -Fc -f "/tmp/backup.dump"
    docker cp "${ContainerName}:/tmp/backup.dump" $BackupFile
    docker exec -t $ContainerName rm -f "/tmp/backup.dump"

    if (Test-Path $BackupFile) {
        $sizeMB = (Get-Item $BackupFile).Length / 1MB
        $hash = (Get-FileHash -Path $BackupFile -Algorithm SHA256).Hash
        Write-Host "`n>>> SAO LƯU THÀNH CÔNG!" -ForegroundColor Green
        Write-Host "  + Dung lượng: $($sizeMB.ToString('F2')) MB"
        Write-Host "  + SHA-256   : $hash"
    } else {
        Write-Error "Không tìm thấy file backup sau khi chạy lệnh."
    }
}
elseif ($Action -eq "restore") {
    if (-not (Test-Path $BackupFile)) {
        Write-Error "File backup không tồn tại: $BackupFile"
    }

    Write-Host "================================================================================" -ForegroundColor Yellow
    Write-Host "BẮT ĐẦU PHỤC HỒI DATABASE (pg_restore) TỪ FILE: $BackupFile" -ForegroundColor Yellow
    Write-Host "  + Container đích: $ContainerName" -ForegroundColor Yellow
    Write-Host "================================================================================"

    docker cp $BackupFile "${ContainerName}:/tmp/restore.dump"
    # Phục hồi với cờ --clean --if-exists để làm sạch dữ liệu cũ
    docker exec -t $ContainerName pg_restore -U $DbUser -d $DbName --clean --if-exists -v "/tmp/restore.dump"
    docker exec -t $ContainerName rm -f "/tmp/restore.dump"

    # Kiểm tra số lượng bản ghi sau phục hồi
    $checkSql = "SELECT count(*) FROM grid_daily_predictions;"
    $rows = docker exec -t $ContainerName psql -U $DbUser -d $DbName -t -c $checkSql
    Write-Host "`n>>> PHỤC HỒI THÀNH CÔNG!" -ForegroundColor Green
    Write-Host "  + Số lượng prediction hiện có: $($rows.Trim()) dòng"
}
