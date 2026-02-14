# Trilium Notes Docker Backup System

A Docker-based scheduled backup solution for Trilium Notes, featuring SQLite hot backups, GPG encryption, and multi-cloud storage support.

## Features

- **Zero-Downtime Backups** - Uses SQLite's `.backup` command for hot backups
- **GPG AES256 Encryption** - Military-grade encryption for all backups
- **Multi-Cloud Support** - Upload to R2, S3, B2, Google Drive via rclone
- **Configurable Scheduling** - Cron-based backup scheduling
- **Retention Policy** - Automatic cleanup of old backups
- **Notifications** - Email and webhook alerts on success/failure
- **Integrity Verification** - SHA256 checksums and metadata

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 2. Configure Cloud Storage (Optional)

```bash
cp backup/rclone.conf.example backup/rclone.conf
# Edit backup/rclone.conf with your cloud credentials
```

### 3. Start Backup Service

#### Option A: Using Pre-built GHCR Image (Recommended)

The docker-compose.yml uses the pre-built GitHub Container Registry (GHCR) image by default:

```bash
# Pull and run the latest image
docker compose --profile backup up -d

# Or set COMPOSE_PROFILES=backup in .env, then:
docker compose up -d
```

Available images at `ghcr.io/your-username/trilium-backup`:
- `latest` - Latest stable release
- `v1.0.0` - Specific version tags
- `main` - Latest development build

Supported platforms: `linux/amd64`, `linux/arm64`

#### Option B: Build Locally

```bash
# Build the backup image locally
docker compose -f docker-compose.yml -f docker-compose.build.yml --profile backup up -d --build
```

### 4. Verify Backup

```bash
# Check backup logs
docker compose logs -f trilium-backup

# List local backups
ls -la ./trilium-docker-backups/
```

## What Gets Backed Up

The backup includes your entire Trilium data directory:

| File | Purpose |
|------|---------|
| `document.db` | Main SQLite database (hot backup) |
| `document.db-shm` | Shared memory file |
| `document.db-wal` | Write-ahead log |
| `config.ini` | Trilium configuration |
| `session_secret.txt` | Session encryption key |
| `log/` | Application logs |
| `backup-metadata.json` | Backup integrity metadata |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRILIUM_LOCAL_DATA_DIR` | `./trilium-data` | Host path to Trilium data |
| `TRILIUM_REMOTE_DATA_DIR` | `/home/node/trilium-data` | Container path to Trilium data |
| `BACKUP_SCHEDULE` | `0 2 * * *` | Cron schedule (default: daily 2 AM) |
| `BACKUP_RETENTION_DAYS` | `30` | Days to keep backups |
| `BACKUP_ENCRYPTION_KEY` | (empty) | GPG passphrase (empty = no encryption) |
| `BACKUP_RCLONE_DESTINATIONS` | (empty) | Comma-separated rclone destinations |
| `BACKUP_RUN_ON_START` | `false` | Run backup immediately on container start |
| `BACKUP_DELETE_LOCAL_AFTER_UPLOAD` | `false` | Delete local copy after cloud upload |
| `BACKUP_WEBHOOK_URL` | (empty) | Webhook URL for notifications |
| `SMTP_HOST` | (empty) | SMTP server for email notifications |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | (empty) | SMTP username |
| `SMTP_PASSWORD` | (empty) | SMTP password |
| `SMTP_TO` | (empty) | Email recipient for notifications |

### Schedule Examples

```bash
# Daily at 2:00 AM
BACKUP_SCHEDULE=0 2 * * *

# Every 6 hours
BACKUP_SCHEDULE=0 */6 * * *

# Weekly on Sunday at 3:00 AM
BACKUP_SCHEDULE=0 3 * * 0

# Twice daily (2 AM and 2 PM)
BACKUP_SCHEDULE=0 2,14 * * *
```

## Cloud Storage Configuration

1. Copy the example rclone config:
```bash
cp backup/rclone.conf.example backup/rclone.conf
```

2. Edit `backup/rclone.conf` with your credentials

3. Set destinations in `.env`:
```bash
BACKUP_RCLONE_DESTINATIONS=r2:my-bucket/trilium-backups,s3:backup-bucket/trilium
```

### Supported Providers

- **Cloudflare R2** - `r2:bucket/path`
- **AWS S3** - `s3:bucket/path`
- **Backblaze B2** - `b2:bucket/path`
- **Google Drive** - `gdrive:folder/path`

## Backup Process

1. **Pre-flight checks** - Verify data directory exists
2. **SQLite hot backup** - Creates consistent snapshot using `.backup`
3. **Archive creation** - Tars database and config files
4. **Encryption** (optional) - GPG AES256 encryption
5. **Cloud upload** (optional) - rclone to configured destinations
6. **Cleanup** - Remove old backups per retention policy
7. **Notifications** - Email/webhook on completion

## Restore from Backup

The backup container includes a restore helper script for easier restoration. **Cloud is the default source** for all operations.

```bash
# List cloud backups (default)
docker compose exec trilium-backup python restore.py --list

# List local backups
docker compose exec trilium-backup python restore.py --list --source local

# Restore latest from cloud (default)
docker compose -f docker-compose.yml -f docker-compose.restore.yml --profile backup run --rm trilium-backup python restore.py --restore-latest

# Restore latest from local
docker compose -f docker-compose.yml -f docker-compose.restore.yml --profile backup run --rm trilium-backup python restore.py --restore-latest --source local

# Restore specific file from cloud (auto-detected by colon)
docker compose -f docker-compose.yml -f docker-compose.restore.yml --profile backup run --rm trilium-backup python restore.py --restore r2:my-bucket/trilium-backup-20250214.tar.gz.gpg

# Restore specific local file
docker compose -f docker-compose.yml -f docker-compose.restore.yml --profile backup run --rm trilium-backup python restore.py --restore trilium-backup-20250214.tar.gz.gpg --source local
```

**Note:** Use `docker-compose.restore.yml` for restore operations - it mounts the Trilium data directory with write access (required for restoring files).

The restore script includes:
- **Cloud-first architecture** - Cloud is the default backup source
- **Auto-detection** - Automatically detects cloud paths (contains `:` like `r2:bucket/file`)
- **Safety checks** - Warns if Trilium is running, creates safety backup
- **Integrity verification** - Validates checksums before restore
- **Automatic decryption** - Handles GPG encrypted backups
- **Confirmation prompts** - Prevents accidental overwrites (use `--force` to skip)

## Testing Backups

Run a one-off backup to test configuration:

```bash
# Set in .env: BACKUP_RUN_ON_START=true
docker compose --profile backup up trilium-backup

# Or run backup manually
docker compose exec trilium-backup python backup.py --run-once
```

## Troubleshooting

### Check Backup Logs
```bash
docker compose logs trilium-backup
```

### Verify SQLite Backup
```bash
# Enter backup container
docker compose exec trilium-backup sh

# Verify sqlite3 is available
sqlite3 --version

# Check database integrity
sqlite3 /trilium-data/document.db "PRAGMA integrity_check;"
```

### Test rclone Configuration
```bash
docker compose exec trilium-backup rclone listremotes --config /config/rclone/rclone.conf
```

### Manual Backup Trigger
```bash
docker compose exec trilium-backup python -c "from backup import run_backup; run_backup()"
```

## Security

- **Encryption**: AES256 symmetric encryption via GPG
- **Permissions**: Backup files created with 0600 (owner read/write only)
- **Read-only mounts**: Trilium data mounted read-only in backup container
- **Passphrase**: Never stored in backup files, only in environment variables

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Trilium       │────▶│  trilium-backup  │────▶│  Cloud Storage  │
│   (document.db) │     │  (Python + GPG)  │     │  (S3/R2/B2/etc) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                        │
        │                        ▼
        │               ┌──────────────────┐
        └──────────────▶│  Local Backups   │
                        │  (encrypted)     │
                        └──────────────────┘
```

## File Structure

```
.
├── docker-compose.yml          # Main compose file (uses GHCR image)
├── docker-compose.build.yml    # Override for local builds
├── docker-compose.restore.yml  # Override for restore operations (write access)
├── .env                        # Environment configuration
├── .env.example                # Example environment file
├── README.md                   # This file
├── .github/
│   └── workflows/
│       └── docker-build.yml    # GitHub Actions for GHCR builds
├── docs/
│   └── BACKUP_RESTORE_GUIDELINE.md # Detailed backup/restore guide
├── trilium-data/               # Trilium data directory
├── trilium-docker-backups/     # Docker backup storage (encrypted)
└── backup/
    ├── Dockerfile              # Backup container image
    ├── backup.py               # Main backup script
    ├── restore.py              # Restore helper script (cloud-first)
    ├── requirements.txt        # Python dependencies
    └── rclone.conf.example     # Cloud storage config template
```

## GitHub Actions

The repository includes a GitHub Actions workflow to automatically build and push multi-arch Docker images to GitHub Container Registry (GHCR).

### Features

- **Multi-architecture support**: Builds for both `linux/amd64` and `linux/arm64`
- **Automatic tagging**: Creates tags for branches, PRs, and semantic versions
- **Public packages**: Images are automatically made public
- **Caching**: Uses GitHub Actions cache for faster builds

### Manual Trigger

You can manually trigger a build from the GitHub Actions tab:

1. Go to **Actions** → **Build and Push Docker Image**
2. Click **Run workflow**
3. Optionally specify a custom tag

### Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest release |
| `main` | Latest commit on main branch |
| `v1.0.0` | Semantic version tags |
| `sha-abc123` | Specific commit SHA |

## License

MIT License - See [LICENSE](LICENSE) for details.

## Credits

Inspired by the [n8n-autoscaling](https://github.com/conor-is-my-name/n8n-autoscaling) backup architecture.