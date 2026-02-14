#!/usr/bin/env python3
"""
Trilium Notes Restore Helper Script

Provides interactive restore functionality with safety checks.
Cloud-first architecture - cloud storage is the primary backup source.
"""

import os
import sys
import json
import shutil
import tarfile
import subprocess
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
BACKUP_DIR = Path('/backups')
TRILIUM_DATA_DIR = Path(os.getenv('TRILIUM_DATA_DIR', '/home/node/trilium-data'))
BACKUP_ENCRYPTION_KEY = os.getenv('BACKUP_ENCRYPTION_KEY', '')
BACKUP_RCLONE_DESTINATIONS = os.getenv('BACKUP_RCLONE_DESTINATIONS', '')
SUBPROCESS_TIMEOUT = 600


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def print_success(text):
    """Print success message."""
    print(f"✓ {text}")


def print_error(text):
    """Print error message."""
    print(f"✗ {text}", file=sys.stderr)


def print_warning(text):
    """Print warning message."""
    print(f"⚠ {text}")


def print_info(text):
    """Print info message."""
    print(f"ℹ {text}")


def is_cloud_path(path):
    """Check if path is a cloud path (contains colon like r2:bucket/file)."""
    return ':' in path and not path.startswith('/') and not path.startswith('./')


def parse_backup_date(filename):
    """Extract date from backup filename."""
    try:
        # Format: trilium-backup-YYYYMMDD-HHMMSS.tar.gz[.gpg]
        parts = filename.replace('trilium-backup-', '').split('.')[0]
        return datetime.strptime(parts, '%Y%m%d-%H%M%S')
    except Exception:
        return None


def get_backup_info(backup_path):
    """Get detailed info about a backup file."""
    info = {
        'filename': backup_path.name,
        'size_mb': backup_path.stat().st_size / (1024 * 1024),
        'modified': datetime.fromtimestamp(backup_path.stat().st_mtime, tz=timezone.utc),
        'encrypted': backup_path.suffix == '.gpg',
    }

    # Try to extract metadata if archive
    if backup_path.suffix == '.gz' or '.tar.gz' in backup_path.name:
        try:
            with tarfile.open(backup_path, 'r:gz') as tar:
                metadata_member = tar.getmember('backup-metadata.json')
                if metadata_member:
                    f = tar.extractfile(metadata_member)
                    if f:
                        metadata = json.loads(f.read().decode('utf-8'))
                        info['metadata'] = metadata
        except Exception:
            pass

    return info


def list_local_backups():
    """List all available local backups with details."""
    print_header("Available Local Backups")

    backups = list(BACKUP_DIR.glob('trilium-backup-*'))
    if not backups:
        print_warning("No local backups found in /backups")
        print("  Run a backup first or check cloud storage.\n")
        return []

    # Sort by modification time (newest first)
    backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    print(f"{'Index':<6} {'Date':<20} {'Size':<12} {'Encrypted':<10} {'Filename'}")
    print("-" * 90)

    for idx, backup in enumerate(backups, 1):
        info = get_backup_info(backup)
        date_str = info['modified'].strftime('%Y-%m-%d %H:%M:%S UTC')
        size_str = f"{info['size_mb']:.1f} MB"
        encrypted_str = "Yes" if info['encrypted'] else "No"

        print(f"{idx:<6} {date_str:<20} {size_str:<12} {encrypted_str:<10} {info['filename']}")

    print()
    return backups


def list_cloud_backups():
    """List backups available in cloud storage."""
    print_header("Available Cloud Backups")

    if not BACKUP_RCLONE_DESTINATIONS:
        print_warning("No cloud destinations configured")
        print("  Set BACKUP_RCLONE_DESTINATIONS in .env\n")
        return []

    destinations = [d.strip() for d in BACKUP_RCLONE_DESTINATIONS.split(',') if d.strip()]
    all_cloud_backups = []

    for dest in destinations:
        print_info(f"Checking {dest}...")
        cmd = [
            'rclone', 'lsf',
            dest,
            '--config', '/config/rclone/rclone.conf',
            '--format', 'st',
            '--include', 'trilium-backup-*'
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip():
                        # Parse rclone lsf output: size;time;filename
                        parts = line.split(';')
                        if len(parts) >= 3:
                            size = int(parts[0])
                            mod_time = parts[1]
                            filename = parts[2]
                            all_cloud_backups.append({
                                'filename': filename,
                                'destination': dest,
                                'size_mb': size / (1024 * 1024),
                                'modified': mod_time
                            })
        except Exception as e:
            print_error(f"Failed to list {dest}: {e}")

    if not all_cloud_backups:
        print_warning("No backups found in cloud storage\n")
        return []

    # Sort by date (newest first)
    all_cloud_backups.sort(key=lambda x: x['modified'], reverse=True)

    print(f"\n{'Index':<6} {'Date':<20} {'Size':<12} {'Destination':<30} {'Filename'}")
    print("-" * 100)

    for idx, backup in enumerate(all_cloud_backups, 1):
        print(f"{idx:<6} {backup['modified']:<20} {backup['size_mb']:.1f} MB{'':<6} {backup['destination']:<30} {backup['filename']}")

    print()
    return all_cloud_backups


def download_from_cloud(remote_path, local_filename=None):
    """Download a backup from cloud storage."""
    if not local_filename:
        local_filename = remote_path.split('/')[-1]

    local_path = BACKUP_DIR / local_filename

    print_info(f"Downloading {remote_path}...")
    cmd = [
        'rclone', 'copyto',
        remote_path, str(local_path),
        '--config', '/config/rclone/rclone.conf',
        '--progress'
    ]

    result = subprocess.run(cmd, timeout=SUBPROCESS_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to download from cloud: {remote_path}")

    print_success(f"Downloaded to {local_path}")
    return local_path


def find_latest_cloud_backup():
    """Find the latest backup in cloud storage."""
    if not BACKUP_RCLONE_DESTINATIONS:
        return None

    destinations = [d.strip() for d in BACKUP_RCLONE_DESTINATIONS.split(',') if d.strip()]
    latest_backup = None

    for dest in destinations:
        cmd = [
            'rclone', 'lsf',
            dest,
            '--config', '/config/rclone/rclone.conf',
            '--format', 'st',
            '--include', 'trilium-backup-*'
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip():
                        parts = line.split(';')
                        if len(parts) >= 3:
                            mod_time = parts[1]
                            filename = parts[2]
                            if not latest_backup or mod_time > latest_backup['modified']:
                                latest_backup = {
                                    'filename': filename,
                                    'destination': dest,
                                    'modified': mod_time
                                }
        except Exception:
            continue

    return latest_backup


def decrypt_backup(encrypted_path, passphrase=None):
    """Decrypt a GPG-encrypted backup."""
    if not encrypted_path.suffix == '.gpg':
        return encrypted_path

    passphrase = passphrase or BACKUP_ENCRYPTION_KEY
    if not passphrase:
        passphrase = input("Enter GPG passphrase: ")

    decrypted_path = encrypted_path.with_suffix('')
    while decrypted_path.suffix == '.gpg':
        decrypted_path = decrypted_path.with_suffix('')

    print_info(f"Decrypting {encrypted_path.name}...")
    cmd = [
        'gpg', '--batch', '--yes', '--decrypt',
        '--passphrase-fd', '0',
        '--output', str(decrypted_path),
        str(encrypted_path)
    ]

    result = subprocess.run(
        cmd, input=passphrase,
        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
    )

    if result.returncode != 0:
        raise RuntimeError(f"Decryption failed: {result.stderr.strip()}")

    print_success(f"Decrypted to {decrypted_path.name}")
    return decrypted_path


def verify_backup(backup_path):
    """Verify backup integrity using metadata checksums."""
    print_info("Verifying backup integrity...")

    try:
        with tarfile.open(backup_path, 'r:gz') as tar:
            metadata_member = tar.getmember('backup-metadata.json')
            if metadata_member:
                f = tar.extractfile(metadata_member)
                if f:
                    metadata = json.loads(f.read().decode('utf-8'))
                    checksums = metadata.get('files', {})

                    all_ok = True
                    for member in tar.getmembers():
                        if member.isfile() and member.name in checksums:
                            expected_hash = checksums[member.name]
                            f = tar.extractfile(member)
                            if f:
                                import hashlib
                                actual_hash = hashlib.sha256(f.read()).hexdigest()
                                if actual_hash != expected_hash:
                                    print_error(f"Checksum mismatch: {member.name}")
                                    all_ok = False

                    if all_ok:
                        print_success("Backup integrity verified")
                        return True
                    else:
                        print_error("Backup integrity check failed!")
                        return False

        print_warning("No metadata found, skipping integrity check")
        return True

    except Exception as e:
        print_error(f"Verification failed: {e}")
        return False


def run_restore(backup_path, trilium_data_dir=None, force=False):
    """Execute restore with safety checks."""
    trilium_data_dir = Path(trilium_data_dir) if trilium_data_dir else TRILIUM_DATA_DIR

    print_header(f"Restoring from {backup_path.name}")

    # Safety checks
    if not backup_path.exists():
        print_error(f"Backup file not found: {backup_path}")
        return False

    if not trilium_data_dir.exists():
        print_error(f"Trilium data directory not found: {trilium_data_dir}")
        return False

    # Check if Trilium is running
    print_info("Checking if Trilium container is running...")
    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'name=trilium', '--format', '{{.Names}}'],
            capture_output=True, text=True, timeout=10
        )
        if 'trilium' in result.stdout.lower():
            if not force:
                print_error("Trilium container is running!")
                print("  Stop Trilium first: docker compose stop trilium")
                print("  Or use --force to attempt restore anyway (NOT RECOMMENDED)")
                return False
            else:
                print_warning("Trilium is running but --force specified. Proceeding...")
    except Exception as e:
        print_warning(f"Could not check Trilium status: {e}")

    # Confirm restore
    if not force:
        print_warning("This will OVERWRITE your current Trilium data!")
        confirm = input("Type 'RESTORE' to confirm: ")
        if confirm != 'RESTORE':
            print("Restore cancelled.")
            return False

    # Create safety backup of current data
    safety_backup = trilium_data_dir.parent / f"trilium-data-safety-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print_info(f"Creating safety backup: {safety_backup}")
    try:
        shutil.copytree(trilium_data_dir, safety_backup)
        print_success(f"Safety backup created")
    except Exception as e:
        print_error(f"Failed to create safety backup: {e}")
        if not force:
            return False

    # Decrypt if needed
    try:
        if backup_path.suffix == '.gpg':
            backup_path = decrypt_backup(backup_path)
    except Exception as e:
        print_error(f"Decryption failed: {e}")
        return False

    # Verify backup
    if not verify_backup(backup_path):
        print_error("Backup verification failed. Aborting restore.")
        return False

    # Extract backup
    print_info("Extracting backup...")
    work_dir = BACKUP_DIR / f"restore-work-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(backup_path, 'r:gz') as tar:
            tar.extractall(path=work_dir, filter='data')

        # Restore files
        files_to_restore = [
            ('document.db', True),
            ('document.db-shm', False),
            ('document.db-wal', False),
            ('config.ini', True),
            ('session_secret.txt', True),
        ]

        for filename, required in files_to_restore:
            src = work_dir / filename
            dst = trilium_data_dir / filename

            if src.exists():
                shutil.copy2(src, dst)
                print_success(f"Restored {filename}")
            elif required:
                print_error(f"Required file missing from backup: {filename}")
                return False

        print_header("Restore Complete")
        print_success("Trilium data restored successfully!")
        print(f"\nNext steps:")
        print(f"  1. Start Trilium: docker compose start trilium")
        print(f"  2. Verify your notes at https://trilium.ts.${os.getenv('DOMAINNAME', 'yourdomain.com')}")
        print(f"  3. Remove safety backup when confirmed: rm -rf {safety_backup}")

        return True

    except Exception as e:
        print_error(f"Restore failed: {e}")
        print(f"\nYou can recover from safety backup: {safety_backup}")
        return False

    finally:
        # Cleanup
        if work_dir.exists():
            shutil.rmtree(work_dir)


def main():
    parser = argparse.ArgumentParser(
        description='Trilium Notes Restore Helper - Cloud-first architecture',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List cloud backups (default)
  python restore.py --list

  # List local backups
  python restore.py --list --source local

  # Restore latest from cloud (default)
  python restore.py --restore-latest

  # Restore latest from local
  python restore.py --restore-latest --source local

  # Restore specific file from cloud (auto-detected)
  python restore.py --restore r2:bucket/trilium-backup-20250214.tar.gz.gpg

  # Restore specific local file
  python restore.py --restore trilium-backup-20250214.tar.gz.gpg --source local
        """
    )

    parser.add_argument('--list', '-l', action='store_true',
                        help='List available backups (default: cloud)')
    parser.add_argument('--restore-latest', '-rl', action='store_true',
                        help='Restore from latest backup (default: cloud)')
    parser.add_argument('--restore', '-r', metavar='PATH',
                        help='Restore from specific backup (auto-detects cloud by colon)')
    parser.add_argument('--source', '-s', choices=['cloud', 'local'], default='cloud',
                        help='Backup source: cloud or local (default: cloud)')
    parser.add_argument('--data-dir', '-d', metavar='PATH',
                        help=f'Trilium data directory (default: {TRILIUM_DATA_DIR})')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Skip confirmation prompts (USE WITH CAUTION)')
    parser.add_argument('--passphrase', '-p', metavar='PASSPHRASE',
                        help='GPG passphrase for decryption')

    args = parser.parse_args()

    # Show help if no arguments
    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    try:
        if args.list:
            if args.source == 'local':
                list_local_backups()
            else:
                list_cloud_backups()

        elif args.restore_latest:
            if args.source == 'local':
                # Restore from latest local backup
                backups = list(BACKUP_DIR.glob('trilium-backup-*'))
                if not backups:
                    print_error("No local backups found!")
                    return 1
                backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                latest = backups[0]
                print_info(f"Using latest local backup: {latest.name}")
                return 0 if run_restore(latest, args.data_dir, args.force) else 1
            else:
                # Restore from latest cloud backup
                print_info("Finding latest cloud backup...")
                latest = find_latest_cloud_backup()
                if not latest:
                    print_error("No cloud backups found!")
                    print("  Check BACKUP_RCLONE_DESTINATIONS configuration")
                    return 1

                remote_path = f"{latest['destination']}/{latest['filename']}"
                print_info(f"Using latest cloud backup: {remote_path}")
                local_path = download_from_cloud(remote_path, latest['filename'])
                return 0 if run_restore(local_path, args.data_dir, args.force) else 1

        elif args.restore:
            # Auto-detect if it's a cloud path
            if is_cloud_path(args.restore):
                # Cloud path specified directly
                print_info(f"Cloud path detected: {args.restore}")
                local_path = download_from_cloud(args.restore)
                return 0 if run_restore(local_path, args.data_dir, args.force) else 1
            elif args.source == 'cloud':
                # Treat as cloud path even without colon (user explicitly wants cloud)
                print_info(f"Using cloud source: {args.restore}")
                local_path = download_from_cloud(args.restore)
                return 0 if run_restore(local_path, args.data_dir, args.force) else 1
            else:
                # Local file
                backup_path = BACKUP_DIR / args.restore
                if not backup_path.exists():
                    print_error(f"Backup not found: {backup_path}")
                    return 1
                return 0 if run_restore(backup_path, args.data_dir, args.force) else 1

        return 0

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        return 1
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
