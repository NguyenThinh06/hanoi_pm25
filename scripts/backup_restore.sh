#!/usr/bin/env bash
# ==============================================================================
# Script sao lưu và phục hồi cơ sở dữ liệu PostgreSQL PM2.5 Hà Nội qua Docker (Gói 4)
# Cách dùng:
#   ./scripts/backup_restore.sh backup
#   ./scripts/backup_restore.sh restore backups/hanoi_pm25_latest.dump
# ==============================================================================
set -euo pipefail

ACTION="${1:-backup}"
BACKUP_FILE="${2:-backups/hanoi_pm25_$(date +%Y%m%d_%H%M%S).dump}"
CONTAINER_NAME="${CONTAINER_NAME:-hanoi_pm25_db}"
DB_USER="${POSTGRES_USER:-hanoi_pm25}"
DB_NAME="${POSTGRES_DB:-hanoi_pm25}"

if [ "$ACTION" = "backup" ]; then
    mkdir -p "$(dirname "$BACKUP_FILE")"
    echo "================================================================================"
    echo "BẮT ĐẦU SAO LƯU DATABASE (pg_dump) QUA DOCKER CONTAINER: $CONTAINER_NAME"
    echo "  + File đích: $BACKUP_FILE"
    echo "================================================================================"

    docker exec -t "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc -f "/tmp/backup.dump"
    docker cp "${CONTAINER_NAME}:/tmp/backup.dump" "$BACKUP_FILE"
    docker exec -t "$CONTAINER_NAME" rm -f "/tmp/backup.dump"

    echo ""
    echo ">>> SAO LƯU THÀNH CÔNG!"
    ls -lh "$BACKUP_FILE"
    sha256sum "$BACKUP_FILE"

elif [ "$ACTION" = "restore" ]; then
    if [ ! -f "$BACKUP_FILE" ]; then
        echo "Lỗi: Không tìm thấy file backup: $BACKUP_FILE" >&2
        exit 1
    fi

    echo "================================================================================"
    echo "BẮT ĐẦU PHỤC HỒI DATABASE (pg_restore) TỪ FILE: $BACKUP_FILE"
    echo "  + Container đích: $CONTAINER_NAME"
    echo "================================================================================"

    docker cp "$BACKUP_FILE" "${CONTAINER_NAME}:/tmp/restore.dump"
    docker exec -t "$CONTAINER_NAME" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists -v "/tmp/restore.dump" || true
    docker exec -t "$CONTAINER_NAME" rm -f "/tmp/restore.dump"

    echo ""
    echo ">>> PHỤC HỒI THÀNH CÔNG!"
    docker exec -t "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT count(*) AS total_predictions FROM grid_daily_predictions;"

else
    echo "Cách dùng: $0 [backup|restore] [tên_file_dump]" >&2
    exit 1
fi
