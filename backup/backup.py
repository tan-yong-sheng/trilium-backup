#!/usr/bin/env python3
"""
Trilium Notes Backup Service

Inspired by n8n-autoscaling backup architecture.
Performs scheduled backups of Trilium SQLite database with encryption and cloud upload.
"""

import os
import sys
import time
import shutil
import tarfile
import logging
import subprocess
import smtplib
import json
import hashlib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv
from croniter import croniter

load_dotenv()

# --- Logging Setup ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Configuration from Environment Variables ---
TRILIUM_DATA_DIR = Path(os.getenv('TRILIUM_DATA_DIR', '/home/node/trilium-data'))

BACKUP_SCHEDULE = os.getenv('BACKUP_SCHEDULE', '0 2 * * *')
BACKUP_RETENTION_DAYS = int(os.getenv('BACKUP_RETENTION_DAYS', '30'))
BACKUP_ENCRYPTION_KEY = os.getenv('BACKUP_ENCRYPTION_KEY', '')
BACKUP_RCLONE_DESTINATIONS = os.getenv('BACKUP_RCLONE_DESTINATIONS', '')
BACKUP_RUN_ON_START = os.getenv('BACKUP_RUN_ON_START', 'false').lower() == 'true'
BACKUP_DELETE_LOCAL_AFTER_UPLOAD = os.getenv('BACKUP_DELETE_LOCAL_AFTER_UPLOAD', 'false').lower() == 'true'
BACKUP_WEBHOOK_URL = os.getenv('BACKUP_WEBHOOK_URL', '')

SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_TO = os.getenv('SMTP_TO', '')

BACKUP_DIR = Path('/backups')
SUBPROCESS_TIMEOUT = 600  # 10 minutes for large backups


def run_sqlite_backup(output_path):
    """Creates a hot backup of the SQLite database using the .backup command."""
    db_path = TRILIUM_DATA_DIR / 'document.db'

    if not db_path.exists():
        raise RuntimeError(f"Trilium database not found at {db_path}")

    logging.info(f"Starting SQLite backup of database at '{db_path}'...")

    # Use SQLite's online backup API for consistent hot backup
    cmd = [
        'sqlite3',
        str(db_path),
        f".backup '{output_path}'"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(f"SQLite backup failed (exit {result.returncode}): {result.stderr.strip()}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logging.info(f"SQLite backup complete: {output_path.name} ({size_mb:.1f} MB)")


def calculate_checksum(file_path):
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def create_metadata(timestamp):
    """Creates backup metadata with file information."""
    db_path = TRILIUM_DATA_DIR / 'document.db'
    metadata = {
        'timestamp': timestamp,
        'version': '1.0.0',
        'source_host': os.uname().nodename,
        'trilium_data_dir': str(TRILIUM_DATA_DIR),
    }

    # Add database info if available
    if db_path.exists():
        try:
            cmd = ['sqlite3', str(db_path), 'PRAGMA page_count; PRAGMA page_size; PRAGMA journal_mode;']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 3:
                    metadata['database'] = {
                        'page_count': int(lines[0]) if lines[0].isdigit() else None,
                        'page_size': int(lines[1]) if lines[1].isdigit() else None,
                        'journal_mode': lines[2] if len(lines) > 2 else 'unknown'
                    }
        except Exception as e:
            logging.warning(f"Could not get database metadata: {e}")

    return metadata


def tar_trilium_data(output_path, sqlite_backup_path, metadata):
    """Creates a compressed tar archive of Trilium data with SQLite backup."""
    logging.info("Archiving Trilium data...")

    # First pass: collect files and calculate checksums
    files_to_add = []
    checksums = {}

    # SQLite backup
    if sqlite_backup_path.exists():
        files_to_add.append((sqlite_backup_path, 'document.db'))
        checksums['document.db'] = calculate_checksum(sqlite_backup_path)
        logging.info(f"  Added document.db (SQLite backup)")

    # Other important files
    important_files = [
        'document.db-shm',
        'document.db-wal',
        'config.ini',
        'session_secret.txt',
    ]

    for filename in important_files:
        file_path = TRILIUM_DATA_DIR / filename
        if file_path.exists():
            files_to_add.append((file_path, filename))
            checksums[filename] = calculate_checksum(file_path)
            logging.info(f"  Added {filename}")
        else:
            logging.debug(f"  Skipping {filename} (not found)")

    # Log directory
    log_dir = TRILIUM_DATA_DIR / 'log'
    if log_dir.exists() and any(log_dir.iterdir()):
        files_to_add.append((log_dir, 'log'))
        logging.info(f"  Added log/ directory")

    # Add checksums to metadata
    metadata['files'] = checksums

    # Write metadata to temp file
    metadata_path = output_path.parent / 'backup-metadata.json'
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    files_to_add.append((metadata_path, 'backup-metadata.json'))

    # Create tar archive with all files
    with tarfile.open(output_path, 'w:gz') as tar:
        for file_path, arcname in files_to_add:
            tar.add(str(file_path), arcname=arcname)

    # Clean up temp metadata file
    metadata_path.unlink()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logging.info(f"Archive complete: {output_path.name} ({size_mb:.1f} MB)")


def encrypt_archive(archive_path):
    """Encrypts the archive with GPG symmetric encryption."""
    if not BACKUP_ENCRYPTION_KEY:
        return archive_path

    logging.info("Encrypting backup archive...")
    encrypted_path = archive_path.with_suffix(archive_path.suffix + '.gpg')
    cmd = [
        'gpg', '--batch', '--yes', '--symmetric',
        '--cipher-algo', 'AES256',
        '--passphrase-fd', '0',
        '--output', str(encrypted_path),
        str(archive_path)
    ]

    result = subprocess.run(
        cmd, input=BACKUP_ENCRYPTION_KEY,
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
    )
    if result.returncode != 0:
        raise RuntimeError(f"GPG encryption failed: {result.stderr.strip()}")

    # Remove unencrypted archive
    archive_path.unlink()
    size_mb = encrypted_path.stat().st_size / (1024 * 1024)
    logging.info(f"Encrypted archive: {encrypted_path.name} ({size_mb:.1f} MB)")
    return encrypted_path


def upload_to_destinations(file_path):
    """Uploads the backup file to all configured rclone destinations."""
    if not BACKUP_RCLONE_DESTINATIONS:
        logging.warning("No BACKUP_RCLONE_DESTINATIONS configured. Backup saved locally only.")
        return

    destinations = [d.strip() for d in BACKUP_RCLONE_DESTINATIONS.split(',') if d.strip()]
    if not destinations:
        logging.warning("No valid rclone destinations found. Backup saved locally only.")
        return

    for dest in destinations:
        dest_path = f"{dest}/{file_path.name}"
        logging.info(f"Uploading to {dest_path}...")
        cmd = [
            'rclone', 'copyto',
            str(file_path), dest_path,
            '--config', '/config/rclone/rclone.conf',
            '--progress'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
        if result.returncode != 0:
            raise RuntimeError(f"rclone upload to '{dest}' failed: {result.stderr.strip()}")
        logging.info(f"Upload to {dest} complete.")


def cleanup_old_backups():
    """Removes local backups older than BACKUP_RETENTION_DAYS."""
    if BACKUP_RETENTION_DAYS <= 0:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=BACKUP_RETENTION_DAYS)
    removed = 0

    for f in BACKUP_DIR.glob('trilium-backup-*'):
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) < cutoff:
            f.unlink()
            removed += 1
            logging.debug(f"Removed old backup: {f.name}")

    if removed:
        logging.info(f"Cleaned up {removed} old local backup(s).")


def cleanup_remote_backups():
    """Removes remote backups older than BACKUP_RETENTION_DAYS using rclone delete."""
    if not BACKUP_RCLONE_DESTINATIONS or BACKUP_RETENTION_DAYS <= 0:
        return

    destinations = [d.strip() for d in BACKUP_RCLONE_DESTINATIONS.split(',') if d.strip()]
    for dest in destinations:
        logging.info(f"Cleaning up old backups on {dest}...")
        cmd = [
            'rclone', 'delete',
            dest,
            '--config', '/config/rclone/rclone.conf',
            '--min-age', f"{BACKUP_RETENTION_DAYS}d",
            '--include', 'trilium-backup-*'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
        if result.returncode != 0:
            logging.warning(f"Remote cleanup on '{dest}' failed: {result.stderr.strip()}")
        else:
            logging.info(f"Remote cleanup on {dest} complete.")


def send_notification(subject, body, is_error=False):
    """Sends a notification via email and/or webhook."""
    if SMTP_HOST and SMTP_TO:
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = SMTP_USER or f"trilium-backup@{os.uname().nodename}"
            msg['To'] = SMTP_TO

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.starttls()
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            logging.info("Email notification sent.")
        except Exception as e:
            logging.error(f"Failed to send email notification: {e}")

    if BACKUP_WEBHOOK_URL:
        try:
            import urllib.request
            payload = json.dumps({
                'event': 'backup_error' if is_error else 'backup_success',
                'subject': subject,
                'body': body,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }).encode('utf-8')
            req = urllib.request.Request(
                BACKUP_WEBHOOK_URL,
                data=payload,
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=30)
            logging.info("Webhook notification sent.")
        except Exception as e:
            logging.error(f"Failed to send webhook notification: {e}")


def run_backup():
    """Executes a single backup cycle."""
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    work_dir = BACKUP_DIR / f"work-{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: Create metadata
        metadata = create_metadata(timestamp)

        # Step 2: SQLite hot backup
        sqlite_backup_path = work_dir / 'document.db'
        run_sqlite_backup(sqlite_backup_path)

        # Step 3: Archive Trilium data
        archive_name = f"trilium-backup-{timestamp}.tar.gz"
        archive_path = BACKUP_DIR / archive_name
        tar_trilium_data(archive_path, sqlite_backup_path, metadata)

        # Step 4: Encrypt if configured
        final_path = encrypt_archive(archive_path)

        # Step 5: Upload to remote destinations
        upload_to_destinations(final_path)

        size_mb = final_path.stat().st_size / (1024 * 1024)

        # Step 6: Delete local copy after successful upload if configured
        if BACKUP_DELETE_LOCAL_AFTER_UPLOAD and BACKUP_RCLONE_DESTINATIONS:
            final_path.unlink()
            logging.info("Local backup deleted after successful remote upload.")

        # Step 7: Cleanup old backups
        cleanup_old_backups()
        cleanup_remote_backups()

        send_notification(
            f"Trilium Backup Successful - {timestamp}",
            f"Backup completed successfully.\n\nFile: {final_path.name}\nSize: {size_mb:.1f} MB\nEncrypted: {'Yes' if BACKUP_ENCRYPTION_KEY else 'No'}\nDestinations: {BACKUP_RCLONE_DESTINATIONS or 'local only'}"
        )
        logging.info(f"Backup cycle complete: {final_path.name}")

    except Exception as e:
        logging.error(f"Backup failed: {e}")
        send_notification(
            f"Trilium Backup FAILED - {timestamp}",
            f"Backup failed with error:\n\n{e}",
            is_error=True
        )
        raise
    finally:
        # Clean up working directory
        if work_dir.exists():
            shutil.rmtree(work_dir)


def main():
    logging.info("Trilium Backup Service starting...")
    logging.info(f"  Data directory: {TRILIUM_DATA_DIR}")
    logging.info(f"  Schedule: {BACKUP_SCHEDULE}")
    logging.info(f"  Retention: {BACKUP_RETENTION_DAYS} days")
    logging.info(f"  Encryption: {'enabled' if BACKUP_ENCRYPTION_KEY else 'disabled'}")
    logging.info(f"  Destinations: {BACKUP_RCLONE_DESTINATIONS or 'local only'}")
    logging.info(f"  Run on start: {BACKUP_RUN_ON_START}")

    # Validate cron expression
    if not croniter.is_valid(BACKUP_SCHEDULE):
        logging.error(f"Invalid BACKUP_SCHEDULE cron expression: '{BACKUP_SCHEDULE}'")
        sys.exit(1)

    # Validate data directory exists
    if not TRILIUM_DATA_DIR.exists():
        logging.error(f"Trilium data directory does not exist: {TRILIUM_DATA_DIR}")
        sys.exit(1)

    # Run immediately on start if configured
    if BACKUP_RUN_ON_START:
        logging.info("Running initial backup on start...")
        try:
            run_backup()
        except Exception:
            logging.error("Initial backup failed, but continuing to schedule future backups.")

    # Schedule loop
    cron = croniter(BACKUP_SCHEDULE, datetime.now(timezone.utc))
    while True:
        next_run = cron.get_next(datetime)
        wait_seconds = (next_run - datetime.now(timezone.utc)).total_seconds()

        if wait_seconds > 0:
            logging.info(f"Next backup scheduled at {next_run.strftime('%Y-%m-%d %H:%M:%S UTC')} (in {wait_seconds/3600:.1f}h)")
            time.sleep(max(wait_seconds, 0))

        try:
            run_backup()
        except Exception:
            logging.error("Backup failed. Will retry at next scheduled time.")


if __name__ == "__main__":
    main()
