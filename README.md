# Trilium Notes Docker Backup System

A Docker-based scheduled backup solution for Trilium Notes, featuring SQLite hot backups, GPG encryption, and multi-cloud storage support.

## Features

- **Zero-Downtime Backups** - Uses SQLite's `.backup` command for hot backups (no Trilium downtime)
- **GPG AES256 Encryption** - Military-grade encryption for all backups
- **Multi-Cloud Support** - Upload to multiple cloud providers simultaneously (R2, S3, B2, etc.)
- **Cloud-First Restore** - Restore directly from cloud storage to any machine
- **Configurable Scheduling** - Cron-based backup scheduling
- **Retention Policy** - Automatic cleanup of old backups
- **Notifications** - Email and webhook alerts on success/failure
- **Integrity Verification** - SHA256 checksums and metadata

## Quick Start (Using GHCR Image)

### 1. Create Required Directories

```bash
mkdir -p trilium-data trilium-docker-backups backup
```

### 2. Configure Environment

Create `.env` file:
(Refer to .env.example)

```bash
cat > .env << 'EOF'
# Trilium Configuration
TRILIUM_LOCAL_DATA_DIR=./trilium-data
TRILIUM_REMOTE_DATA_DIR=/home/node/trilium-data

# Backup Configuration
BACKUP_SCHEDULE=0 2 * * *
BACKUP_RETENTION_DAYS=30
BACKUP_ENCRYPTION_KEY=your-secure-gpg-passphrase-here
BACKUP_RCLONE_DESTINATIONS=r2:triliumbackup
BACKUP_RUN_ON_START=false

# SMTP for notifications (optional)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_TO=
EOF
```

> **Note:** Change `BACKUP_ENCRYPTION_KEY` to a secure passphrase. You'll need this to restore backups!

### 3. Configure Cloud Storage (rclone.conf)

Create `backup/rclone.conf` for your cloud provider:
(See backup/rclone.conf.example as reference)

#### Cloudflare R2 (Recommended)

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

#### AWS S3

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

#### Backblaze B2

```bash
cat > backup/rclone.conf << 'EOF'
[b2]
type = b2
account = your-application-key-id
key = your-application-key
EOF
```

#### Multiple Cloud Destinations

You can backup to multiple clouds simultaneously:

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

Then set in `.env`:
```bash
BACKUP_RCLONE_DESTINATIONS=r2:triliumbackup,r2_backup:triliumbackup,s3:trilium-backups
```

### 4. Start Backup Service

```bash
# Start with backup enabled
docker compose --profile backup up -d

# Or set COMPOSE_PROFILES=backup in .env, then simply:
# docker compose up -d
```

### 5. Verify It's Working

```bash
# Check logs
docker compose logs -f trilium-backup

# Test backup manually
docker compose exec trilium-backup python -c "from backup import run_backup; run_backup()"

# List cloud backups
docker compose exec trilium-backup rclone ls r2:triliumbackup --config /config/rclone/rclone.conf
```

## Restore from Backup

### Restore Latest from Cloud (Recommended)

```bash
# Stop Trilium first
docker compose stop trilium

# Restore latest backup from any cloud
docker compose exec trilium-backup python restore.py --restore-latest --force

# Start Trilium
docker compose start trilium
```

### Restore Specific Version from Cloud

```bash
# List available backups
docker compose exec trilium-backup python restore.py --list

# Restore specific backup (use --force to skip confirmation)
docker compose stop trilium
docker compose exec trilium-backup python restore.py --restore r2:triliumbackup/trilium-backup-20250214-120000.tar.gz.gpg --force
docker compose start trilium
```

### Restore from Local Backup

```bash
docker compose stop trilium
docker compose exec trilium-backup python restore.py --restore-latest --source local --force
docker compose start trilium
```

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_SCHEDULE` | `0 2 * * *` | Cron schedule (default: daily 2 AM) |
| `BACKUP_RETENTION_DAYS` | `30` | Days to keep backups locally and in cloud |
| `BACKUP_ENCRYPTION_KEY` | (empty) | GPG passphrase (required for encryption) |
| `BACKUP_RCLONE_DESTINATIONS` | (empty) | Comma-separated rclone destinations |
| `BACKUP_RUN_ON_START` | `false` | Run backup immediately when container starts |
| `BACKUP_DELETE_LOCAL_AFTER_UPLOAD` | `false` | Delete local backup after cloud upload |
| `BACKUP_WEBHOOK_URL` | (empty) | Webhook URL for notifications |
| `SMTP_HOST` | (empty) | SMTP server for email notifications |

### Cron Schedule Examples

```bash
# Every day at 2 AM
BACKUP_SCHEDULE=0 2 * * *

# Every 6 hours
BACKUP_SCHEDULE=0 */6 * * *

# Weekly on Sunday at 3 AM
BACKUP_SCHEDULE=0 3 * * 0

# Every 12 hours
BACKUP_SCHEDULE=0 */12 * * *
```

## Available GHCR Images

| Image | Description |
|-------|-------------|
| `ghcr.io/tan-yong-sheng/trilium-backup:latest` | Latest stable release |
| `ghcr.io/tan-yong-sheng/trilium-backup:main` | Latest development build |
| `ghcr.io/tan-yong-sheng/trilium-backup:v1.0.0` | Specific version |

**Supported platforms:** `linux/amd64`, `linux/arm64`

## Disaster Recovery Workflow

**Scenario:** Server crashed, need to restore on new machine

```bash
# 1. On new server, clone this repo
git clone https://github.com/tan-yong-sheng/trilium-backup.git
cd trilium-backup

# 2. Create .env with your encryption key
cat > .env << 'EOF'
BACKUP_ENCRYPTION_KEY=your-secure-gpg-passphrase-here
BACKUP_RCLONE_DESTINATIONS=r2:triliumbackup
EOF

# 3. Set up rclone.conf with your cloud credentials
# (copy from secure location or recreate)

# 4. Start backup container
docker compose --profile backup up -d

# 5. Restore latest backup from cloud
docker compose exec trilium-backup python restore.py --restore-latest --force

# 6. Start Trilium (assuming you have Trilium configured)
docker compose start trilium
```

## Testing Your Setup

```bash
# Test 1: Run backup immediately
BACKUP_RUN_ON_START=true docker compose --profile backup up trilium-backup

# Test 2: Verify cloud upload
docker compose exec trilium-backup rclone ls r2:triliumbackup --config /config/rclone/rclone.conf

# Test 3: Test restore (creates safety backup automatically)
docker compose stop trilium
docker compose exec trilium-backup python restore.py --restore-latest --force
```

## Troubleshooting

### Check Backup Logs
```bash
docker compose logs trilium-backup
```

### Test rclone Configuration
```bash
docker compose exec trilium-backup rclone listremotes --config /config/rclone/rclone.conf
docker compose exec trilium-backup rclone ls r2:triliumbackup --config /config/rclone/rclone.conf
```

### Manual Backup Trigger
```bash
docker compose exec trilium-backup python -c "from backup import run_backup; run_backup()"
```

### Database Integrity Check
```bash
docker compose exec trilium-backup sqlite3 /trilium-data/document.db "PRAGMA integrity_check;"
```

## Security Notes

- **Encryption Key:** Store `BACKUP_ENCRYPTION_KEY` securely (password manager). You'll need it to restore!
- **rclone.conf:** Contains cloud credentials - keep it secure and don't commit to git
- **Permissions:** Backup files are created with 0600 (owner read/write only)
- **Passphrase:** Never stored in backup files, only verified during restore

## Multi-Cloud Backup Example

Backup to multiple providers for redundancy:

```bash
# .env file
BACKUP_RCLONE_DESTINATIONS=r2:triliumbackup,s3:trilium-backups,b2:trilium-backup-bucket
BACKUP_ENCRYPTION_KEY=your-secure-key
```

```bash
# backup/rclone.conf
[r2]
type = s3
provider = Cloudflare
...

[s3]
type = s3
provider = AWS
...

[b2]
type = b2
...
```

This backs up simultaneously to R2, S3, and B2. If one provider fails, you have two others!

## File Structure

```
.
├── docker-compose.yml          # Main compose file (uses GHCR image)
├── .env                        # Your configuration (secrets here)
├── backup/
│   └── rclone.conf             # Cloud credentials (keep secure!)
├── trilium-data/               # Trilium data (mounted read-only)
└── trilium-docker-backups/     # Local backups (if not using cloud)
```

## License

MIT License - See [LICENSE](LICENSE) for details.

## Credits

Inspired by the [n8n-autoscaling](https://github.com/conor-is-my-name/n8n-autoscaling) backup architecture.
