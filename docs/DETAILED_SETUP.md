# Detailed Setup Guide

Complete step-by-step guide for setting up Trilium Notes backup.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Cloud Storage Configuration](#cloud-storage-configuration)
4. [Environment Configuration](#environment-configuration)
5. [Testing Your Setup](#testing-your-setup)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

- Docker and Docker Compose installed
- Trilium Notes already running (or planning to run)
- Cloud storage account (R2, S3, B2, etc.)

## Initial Setup

### 1. Create Directory Structure

```bash
mkdir -p trilium-backup && cd trilium-backup
mkdir -p trilium-data trilium-docker-backups backup
```

### 2. Download Latest Release

```bash
curl -LO https://raw.githubusercontent.com/tan-yong-sheng/trilium-backup/main/docker-compose.yml
curl -LO https://raw.githubusercontent.com/tan-yong-sheng/trilium-backup/main/.env.example
curl -LO https://raw.githubusercontent.com/tan-yong-sheng/trilium-backup/main/backup/rclone.conf.example
```

Or clone the repository:

```bash
git clone https://github.com/tan-yong-sheng/trilium-backup.git
cd trilium-backup
```

## Cloud Storage Configuration

### Cloudflare R2 (Recommended)

1. Create R2 bucket at https://dash.cloudflare.com
2. Generate API token with R2 access
3. Create `backup/rclone.conf`:

```bash
cat > backup/rclone.conf << 'EOF'
[r2]
type = s3
provider = Cloudflare
access_key_id = your-access-key-id
secret_access_key = your-secret-access-key
endpoint = https://your-account-id.r2.cloudflarestorage.com
acl = private
EOF
```

### AWS S3

```bash
cat > backup/rclone.conf << 'EOF'
[s3]
type = s3
provider = AWS
access_key_id = your-access-key-id
secret_access_key = your-secret-access-key
region = us-east-1
acl = private
EOF
```

### Backblaze B2

```bash
cat > backup/rclone.conf << 'EOF'
[b2]
type = b2
account = your-application-key-id
key = your-application-key
EOF
```

### Multiple Cloud Destinations

For redundancy, backup to multiple providers:

```bash
cat > backup/rclone.conf << 'EOF'
[r2]
type = s3
provider = Cloudflare
...

[r2_backup]
type = s3
provider = Cloudflare
...

[s3]
type = s3
provider = AWS
...
EOF
```

## Environment Configuration

Copy and edit `.env`:

```bash
cp .env.example .env
```

### Required Settings

```bash
# Encryption key - generate a strong one
BACKUP_ENCRYPTION_KEY=$(openssl rand -base64 32)

# Cloud destinations (match your rclone.conf)
BACKUP_RCLONE_DESTINATIONS=r2:my-bucket/trilium-backups
```

### Optional Settings

```bash
# Backup schedule (cron format)
BACKUP_SCHEDULE=0 2 * * *      # Daily at 2 AM
BACKUP_SCHEDULE=0 */6 * * *    # Every 6 hours
BACKUP_SCHEDULE=0 3 * * 0      # Weekly Sunday 3 AM

# Retention
BACKUP_RETENTION_DAYS=30

# Run backup immediately on start (for testing)
BACKUP_RUN_ON_START=false

# Delete local backup after cloud upload (save disk space)
BACKUP_DELETE_LOCAL_AFTER_UPLOAD=false
```

### Email Notifications (Optional)

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_TO=alerts@yourdomain.com
```

## Testing Your Setup

### Test 1: Configuration Check

```bash
# Verify rclone can connect
docker compose --profile backup run --rm trilium-backup rclone listremotes --config /config/rclone/rclone.conf

# List cloud bucket
docker compose --profile backup run --rm trilium-backup rclone ls r2:my-bucket --config /config/rclone/rclone.conf
```

### Test 2: Run Backup Manually

```bash
# Start with immediate backup
BACKUP_RUN_ON_START=true docker compose --profile backup up trilium-backup

# Watch logs
docker compose logs -f trilium-backup
```

### Test 3: Test Restore

```bash
# Stop Trilium
docker compose stop trilium

# Restore from cloud
docker compose exec trilium-backup python restore.py --restore-latest --force

# Start Trilium
docker compose start trilium
```

## Troubleshooting

### Check Logs

```bash
docker compose logs trilium-backup
```

### Verify Environment Variables

```bash
docker compose exec trilium-backup env | grep BACKUP
```

### Test rclone Configuration

```bash
docker compose exec trilium-backup rclone ls r2:my-bucket --config /config/rclone/rclone.conf
```

### Database Integrity Check

```bash
docker compose exec trilium-backup sqlite3 /trilium-data/document.db "PRAGMA integrity_check;"
```

### Common Issues

**Issue:** "No cloud backups found!"
**Solution:** Check `BACKUP_RCLONE_DESTINATIONS` matches your rclone.conf remote name

**Issue:** "Failed to download from cloud"
**Solution:** Verify rclone credentials and endpoint in `backup/rclone.conf`

**Issue:** "Decryption failed"
**Solution:** Ensure `BACKUP_ENCRYPTION_KEY` matches the key used for backup

## Next Steps

- See [.env.example](../.env.example) for all configuration options
- See [backup/rclone.conf.example](../backup/rclone.conf.example) for more cloud provider examples
