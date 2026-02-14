# Trilium Notes Backup & Restore Guideline

## Overview

This document outlines the proposed backup and restore strategy for Trilium Notes Docker deployment, adapted from the proven n8n-autoscaling backup architecture.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Trilium Backup Service                              │
│                                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │   Trilium   │───▶│   Backup     │───▶│   GPG       │───▶│   rclone    │ │
│  │   Container │    │   Container  │    │   Encrypt   │    │   Upload    │ │
│  │  (SQLite)   │    │   (Python)   │    │   (AES256)  │    │   (Cloud)   │ │
│  └─────────────┘    └──────────────┘    └─────────────┘    └─────────────┘ │
│                            │                                                │
│                            ▼                                                │
│                     ┌──────────────┐                                        │
│                     │   Local      │                                        │
│                     │   Retention  │                                        │
│                     │   (30 days)  │                                        │
│                     └──────────────┘                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## What Gets Backed Up

The backup includes the entire Trilium data directory:

| File/Directory | Purpose | Critical |
|----------------|---------|----------|
| `document.db` | Main SQLite database with all notes | **YES** |
| `document.db-shm` | Shared memory file for WAL mode | **YES** |
| `document.db-wal` | Write-Ahead Log (uncommitted changes) | **YES** |
| `config.ini` | Trilium configuration | Yes |
| `session_secret.txt` | Session encryption key | Yes |
| `log/` | Application logs | No |
| `tmp/` | Temporary files | No |
| `backup/` | Trilium's internal backups | No |

**Total backup size estimate:** Typically 10MB-1GB depending on note count and attachments.

**Note:** Docker backups are stored separately in `trilium-docker-backups/` (not `trilium-data/backup/`) to avoid mixing with Trilium's native backups. Our backups are GPG-encrypted and have a different format.

---

## Backup Process Flow

### 1. Trigger (Scheduled or Manual)

```
Cron Schedule: 0 2 * * * (Daily at 2:00 AM)
Or: Manual trigger via docker compose exec
```

### 2. Pre-Backup Checks

- Verify Trilium container is running
- Check disk space (need 2x current data size)
- Verify write permissions to backup directory

### 3. SQLite Hot Backup (Zero Downtime)

**Method: SQLite Online Backup API**

```bash
# Create consistent snapshot without stopping Trilium
sqlite3 /data/trilium-data/document.db ".backup '/backup/work/document.db'"
```

**Why this method?**
- No need to stop the Trilium container
- Creates transaction-consistent copy
- Handles WAL files correctly
- Works while Trilium is actively writing

### 4. Archive Creation

```
Backup Structure:
trilium-backup-20250214-030000.tar.gz
├── document.db          (SQLite database copy)
├── document.db-shm      (Shared memory)
├── document.db-wal      (Write-ahead log)
├── config.ini           (Configuration)
├── session_secret.txt   (Session secrets)
├── log/                 (Optional logs)
└── backup-metadata.json (Timestamp, version, checksums)
```

### 5. GPG Encryption (Optional but Recommended)

```bash
# AES256 symmetric encryption with passphrase
gpg --batch --yes --symmetric \
    --cipher-algo AES256 \
    --passphrase "$BACKUP_ENCRYPTION_KEY" \
    --output backup.tar.gz.gpg \
    backup.tar.gz
```

**Security Features:**
- AES256 encryption (military-grade)
- Passphrase never stored in backup files
- Original unencrypted file deleted after encryption

### 6. Cloud Upload via rclone

**Supported Destinations:**
- Cloudflare R2 (S3-compatible)
- AWS S3
- Backblaze B2
- Google Drive
- Any rclone-supported storage

```bash
# Example: Upload to multiple destinations
rclone copyto backup.tar.gz.gpg r2:my-bucket/trilium-backups/
rclone copyto backup.tar.gz.gpg s3:backup-bucket/trilium/
```

### 7. Cleanup & Retention

**Local Cleanup:**
- Remove temporary working files
- Delete local backups older than retention period
- Optionally delete local backup after successful cloud upload

**Remote Cleanup:**
- Remove cloud backups older than retention period
- Uses rclone delete with age filter

### 8. Notifications

**On Success:**
- Email notification with backup size, duration, destinations
- Webhook POST to configured URL

**On Failure:**
- Immediate email alert with error details
- Webhook notification
- Retry at next scheduled interval

---

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_SCHEDULE` | `0 2 * * *` | Cron expression for backup timing |
| `BACKUP_RETENTION_DAYS` | `30` | Days to keep backups locally and remotely |
| `BACKUP_ENCRYPTION_KEY` | (empty) | GPG passphrase (empty = no encryption) |
| `BACKUP_RCLONE_DESTINATIONS` | (empty) | Comma-separated rclone destinations |
| `BACKUP_RUN_ON_START` | `false` | Run backup immediately when container starts |
| `BACKUP_DELETE_LOCAL_AFTER_UPLOAD` | `false` | Delete local copy after cloud upload |
| `BACKUP_WEBHOOK_URL` | (empty) | URL to POST backup status notifications |
| `SMTP_HOST` | (empty) | Email notification server |
| `SMTP_PORT` | `587` | Email server port |
| `SMTP_USER` | (empty) | Email username |
| `SMTP_PASSWORD` | (empty) | Email password |
| `SMTP_TO` | (empty) | Notification email recipient |

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

---

## Restore Process

### Prerequisites

1. Docker and Docker Compose installed
2. Trilium container stopped (for full restore)
3. Backup file accessible (local or download from cloud)
4. GPG passphrase (if backup was encrypted)

### Full Restore (Disaster Recovery)

**Scenario:** Complete data loss, restore from backup to new server

```bash
# Step 1: Stop Trilium container
docker compose stop trilium

# Step 2: Download backup from cloud (if needed)
rclone copy r2:my-bucket/trilium-backups/trilium-backup-20250214-030000.tar.gz.gpg ./

# Step 3: Decrypt backup (if encrypted)
gpg --decrypt \
    --passphrase "YOUR_ENCRYPTION_KEY" \
    trilium-backup-20250214-030000.tar.gz.gpg \
    > trilium-backup-20250214-030000.tar.gz

# Step 4: Extract backup
tar xzf trilium-backup-20250214-030000.tar.gz

# Step 5: Backup current data (if any exists)
mv trilium-data trilium-data.old.$(date +%Y%m%d)

# Step 6: Restore data
cp -r trilium-backup-20250214-030000/* trilium-data/

# Step 7: Set correct permissions
chown -R $(id -u):$(id -g) trilium-data/
chmod -R u+rw trilium-data/

# Step 8: Start Trilium
docker compose start trilium

# Step 9: Verify
# - Access Trilium web UI
# - Check notes are present
# - Verify attachments

# Step 10: Clean up
rm -rf trilium-backup-20250214-030000/
rm trilium-backup-20250214-030000.tar.gz*
```

### Partial Restore (Single Note Recovery)

**Scenario:** Accidental note deletion, want to extract from backup

```bash
# Step 1: Decrypt and extract backup
gpg --decrypt backup.tar.gz.gpg > backup.tar.gz
tar xzf backup.tar.gz

# Step 2: Mount backup as read-only volume for inspection
docker run --rm -it \
  -v $(pwd)/trilium-backup:/backup:ro \
  -v $(pwd)/inspect:/inspect \
  alpine:latest sh

# Step 3: Inside container, use sqlite3 to query
cd /backup
sqlite3 document.db "SELECT title FROM notes WHERE noteId = 'YOUR_NOTE_ID';"

# Step 4: Export specific note content
sqlite3 document.db "SELECT content FROM note_contents WHERE noteId = 'YOUR_NOTE_ID';" > /inspect/note_content.html

# Step 5: Copy from inspect folder and manually recreate in Trilium
```

### Point-in-Time Recovery

**Scenario:** Restore to specific date

```bash
# List available backups
ls -la trilium-backup-*.tar.gz*

# Or list from cloud
rclone ls r2:my-bucket/trilium-backups/

# Choose specific backup by date
docker compose exec trilium-backup python restore.py --restore-latest --source local
```

---

## Restore Helper Script

The `restore.py` script provides an interactive way to restore backups with **cloud-first architecture**.

### Commands

| Command | Description | Default Source |
|---------|-------------|----------------|
| `--list` | List available backups | Cloud |
| `--list --source local` | List local backups only | Local |
| `--restore-latest` | Restore from latest backup | Cloud |
| `--restore-latest --source local` | Restore from latest local backup | Local |
| `--restore <path>` | Restore specific backup | Auto-detect by `:` |
| `--restore <file> --source local` | Restore specific local file | Local |
| `--force` | Skip confirmation prompts | - |

### Examples

```bash
# List cloud backups (default)
docker compose exec trilium-backup python restore.py --list

# List local backups
docker compose exec trilium-backup python restore.py --list --source local

# Restore latest from cloud
docker compose exec trilium-backup python restore.py --restore-latest

# Restore from cloud with specific file
docker compose exec trilium-backup python restore.py --restore r2:bucket/trilium-backup-20250214.tar.gz.gpg

# Restore from local file
docker compose exec trilium-backup python restore.py --restore trilium-backup-20250214.tar.gz.gpg --source local
```

### Auto-Detection Logic

- **Cloud path**: Contains `:` (e.g., `r2:bucket/file`, `s3:bucket/file`)
- **Local path**: Starts with `/`, `./`, or plain filename
- **Override**: Use `--source cloud` or `--source local` to force source

---

## Backup Integrity Verification

### Automatic Verification

Each backup includes a `backup-metadata.json` file:

```json
{
  "timestamp": "2025-02-14T03:00:00Z",
  "version": "1.0.0",
  "source_host": "trilium-server",
  "files": {
    "document.db": {
      "size": 104857600,
      "sha256": "a1b2c3d4e5f6..."
    },
    "config.ini": {
      "size": 3086,
      "sha256": "f6e5d4c3b2a1..."
    }
  },
  "database": {
    "sqlite_version": "3.45.0",
    "page_count": 25600,
    "page_size": 4096,
    "journal_mode": "wal"
  }
}
```

### Manual Verification

```bash
# Verify archive integrity
tar tzf backup.tar.gz > /dev/null && echo "Archive OK" || echo "Archive corrupted"

# Verify SQLite database
sqlite3 document.db "PRAGMA integrity_check;"

# Verify checksums
cd extracted_backup/
sha256sum -c checksums.sha256
```

---

## Security Considerations

### Encryption

- **Algorithm:** AES256 (symmetric)
- **Key Management:** Passphrase stored in environment variable only
- **Transmission:** HTTPS for cloud uploads
- **At Rest:** Encrypted files on both local and cloud storage

### Access Control

- Backup container runs with limited permissions
- Backup files created with 0600 permissions (owner read/write only)
- rclone config stored read-only in container

### Backup Lifecycle

```
1. Create backup in memory/work directory
2. Encrypt in-place
3. Upload to cloud (encrypted)
4. Delete unencrypted working files
5. Retain encrypted local copy (optional)
6. Purge old backups per retention policy
```

---

## Disaster Recovery Scenarios

### Scenario 1: Accidental Note Deletion
**Recovery Time:** 5-10 minutes
1. Stop Trilium
2. Restore from most recent backup
3. Restart Trilium

### Scenario 2: Database Corruption
**Recovery Time:** 10-15 minutes
1. Stop Trilium
2. Backup corrupted database (for forensics)
3. Restore from most recent valid backup
4. Check integrity
5. Restart Trilium

### Scenario 3: Complete Server Loss
**Recovery Time:** 30-60 minutes
1. Provision new server
2. Install Docker
3. Clone Trilium compose files
4. Download backup from cloud
5. Decrypt and restore
6. Start Trilium
7. Verify functionality

### Scenario 4: Ransomware Attack
**Recovery Time:** 30-60 minutes
1. Isolate infected system
2. Provision clean server
3. Restore from encrypted cloud backups
4. Verify no malware in backup
5. Resume operations

---

## Comparison: Built-in Trilium Backup vs This Solution

| Feature | Trilium Built-in | This Backup Solution |
|---------|------------------|---------------------|
| Automatic scheduling | ✅ Periodic-based | ✅ Cron-based |
| Cloud storage | ❌ Local only | ✅ Multi-destination |
| Encryption at rest | ❌ Not encrypted | ✅ AES256 GPG |
| Compression | ✅ Yes | ✅ Yes |
| Versioning/retention | ❌ Single backup | ✅ Configurable retention |
| Notifications | ❌ None | ✅ Email + Webhook |
| Integrity verification | ❌ No | ✅ SHA256 checksums |
| Multi-server backup | ❌ No | ✅ Yes |
| Disaster recovery | ⚠️ Limited | ✅ Full DR capable |

---

## Testing Your Backup

### Monthly Backup Test Procedure

```bash
# 1. Create test environment
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d

# 2. Restore latest backup to test instance
docker compose exec trilium-backup restore-latest --to-test

# 3. Verify data integrity
# - Login to test Trilium
# - Verify note count matches
# - Check recent changes present
# - Verify attachments

# 4. Document test results
# 5. Clean up test environment
```

---

## File Locations

| Component | Path |
|-----------|------|
| Trilium data | `./trilium-data/` |
| Docker backups (encrypted) | `./trilium-docker-backups/` |
| Backup config | `.env` |
| rclone config | `./backup/rclone.conf` |
| Backup script | `./backup/backup.py` |
| Restore script | `./backup/restore.py` |

---

## Implementation Status

✅ **Complete** - All components implemented:

1. **backup/Dockerfile** - Python-based backup container with sqlite3, rclone, gpg
2. **backup/backup.py** - Main backup logic with SQLite hot backup support
3. **backup/restore.py** - Interactive restore helper with safety checks
4. **backup/rclone.conf.example** - Cloud storage configuration template
5. **docker-compose.yml** - Updated with backup service profile
6. **.env.example** - Environment variables documented

## Quick Reference

### Backup Commands
```bash
# Start backup service
docker compose --profile backup up -d

# List backups
docker compose exec trilium-backup python restore.py --list

# Manual backup trigger
docker compose exec trilium-backup python -c "from backup import run_backup; run_backup()"
```

### Restore Commands
```bash
# Restore latest
docker compose exec trilium-backup python restore.py --restore-latest

# Restore specific
docker compose exec trilium-backup python restore.py --restore trilium-backup-20250214-030000.tar.gz.gpg

# Restore from cloud
docker compose exec trilium-backup python restore.py --restore-from-cloud r2:bucket/backup.tar.gz.gpg
```
