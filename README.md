# Trilium Notes Docker Backup System

[![Docker Image](https://github.com/tan-yong-sheng/trilium-backup/actions/workflows/docker-build.yml/badge.svg)](https://github.com/tan-yong-sheng/trilium-backup/actions/workflows/docker-build.yml)
[![E2E Tests](https://github.com/tan-yong-sheng/trilium-backup/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/tan-yong-sheng/trilium-backup/actions/workflows/e2e-test.yml)

A Docker-based scheduled backup solution for Trilium Notes with SQLite hot backups, GPG encryption, and multi-cloud storage support.

## Features

- **Zero-Downtime Backups** - Uses SQLite's `.backup` command (no Trilium downtime)
- **GPG AES256 Encryption** - Military-grade encryption for all backups
- **Multi-Cloud Support** - Upload to multiple cloud providers simultaneously
- **Cloud-First Restore** - Restore directly from cloud to any machine
- **Automated Scheduling** - Cron-based backup scheduling

## Quick Start

### 1. Setup Files

```bash
mkdir -p trilium-data trilium-docker-backups backup
cp .env.example .env
cp backup/rclone.conf.example backup/rclone.conf
```

### 2. Configure Environment

Edit `.env` (see [.env.example](.env.example) for all options):

```bash
# Required
BACKUP_ENCRYPTION_KEY=your-secure-passphrase-here
BACKUP_RCLONE_DESTINATIONS=r2:my-bucket/trilium-backups

# Optional - defaults shown
BACKUP_SCHEDULE=0 2 * * *      # Daily at 2 AM
BACKUP_RETENTION_DAYS=30
```

### 3. Configure Cloud Storage

Edit `backup/rclone.conf` (see [rclone.conf.example](backup/rclone.conf.example) for examples):

```bash
[r2]
type = s3
provider = Cloudflare
access_key_id = your-key
secret_access_key = your-secret
endpoint = https://your-account.r2.cloudflarestorage.com
acl = private
```

### 4. Start Backup Service

```bash
docker compose --profile backup up -d
```

### 5. Verify

```bash
docker compose logs -f trilium-backup
```

## Restore from Backup

```bash
# Stop Trilium
docker compose stop trilium

# Restore latest from cloud
docker compose exec trilium-backup python restore.py --restore-latest --force

# Start Trilium
docker compose start trilium
```

## Documentation

| Document | Description |
|----------|-------------|
| [.env.example](.env.example) | All environment variables explained |
| [backup/rclone.conf.example](backup/rclone.conf.example) | Cloud storage configuration examples |
| [docs/BACKUP_RESTORE_GUIDELINE.md](docs/BACKUP_RESTORE_GUIDELINE.md) | Detailed backup/restore guide |
| [docs/DETAILED_SETUP.md](docs/DETAILED_SETUP.md) | Step-by-step setup tutorial |

## Available Images

```
ghcr.io/tan-yong-sheng/trilium-backup:latest
ghcr.io/tan-yong-sheng/trilium-backup:main
```

Supported: `linux/amd64`, `linux/arm64`

## Disaster Recovery

On a new server:

```bash
git clone https://github.com/tan-yong-sheng/trilium-backup.git
cd trilium-backup
# Copy your .env and backup/rclone.conf
docker compose --profile backup up -d
docker compose exec trilium-backup python restore.py --restore-latest --force
```

## License

MIT License - See [LICENSE](LICENSE)

Inspired by [n8n-autoscaling](https://github.com/conor-is-my-name/n8n-autoscaling)
