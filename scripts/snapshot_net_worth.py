#!/usr/bin/env python3
"""
Net Worth Snapshot Script

Creates daily snapshots of today's net worth (Assets, Liabilities, Net Worth)
and stores them in the net_worth_history table.

Features:
- Always snapshots today's date (historical dates handled by separate backfill script)
- Uses UPSERT logic to prevent duplicates (safe for multiple runs per day)
- Lock file prevents concurrent execution

Usage:
    python scripts/snapshot_net_worth.py

Example cron (daily at 11:59 PM):
    59 23 * * * cd /path && python scripts/snapshot_net_worth.py >> logs/snapshot.log 2>&1
"""

import argparse
import fcntl
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def setup_logging(log_dir: Path) -> logging.Logger:
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # Monthly log rotation
    log_file = log_dir / f"snapshot_{datetime.now().strftime('%Y%m')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class LockFile:
    """Context manager for file-based locking."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock_file = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self.lock_path, "w")
        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_file.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
            self.lock_file.flush()
            return self
        except IOError:
            self.lock_file.close()
            raise RuntimeError(
                f"Another instance is already running (lock file: {self.lock_path})"
            )

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            try:
                self.lock_path.unlink()
            except:
                pass


def get_net_worth_summary(db_path: str):
    """
    Calculate today's net worth summary using the net_worth_summary view.

    Args:
        db_path: Path to SQLite database

    Returns:
        Dict with assets, liabilities, net worth in IDR and USD
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Query the net_worth_summary view for today's data
    query = """
        SELECT
            MAX(CASE WHEN category = 'Assets' THEN total_idr ELSE 0 END) as assets_idr,
            MAX(CASE WHEN category = 'Assets' THEN total_usd ELSE 0 END) as assets_usd,
            MAX(CASE WHEN category = 'Liabilities' THEN total_idr ELSE 0 END) as liabilities_idr,
            MAX(CASE WHEN category = 'Liabilities' THEN total_usd ELSE 0 END) as liabilities_usd,
            (SELECT COUNT(*) FROM latest_balances) as num_balances
        FROM net_worth_summary
        WHERE category IN ('Assets', 'Liabilities')
    """
    cursor = conn.execute(query)
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    # Calculate net worth
    assets_idr = row["assets_idr"] or 0
    assets_usd = row["assets_usd"] or 0
    liabilities_idr = row["liabilities_idr"] or 0
    liabilities_usd = row["liabilities_usd"] or 0

    return {
        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
        "assets_idr": assets_idr,
        "assets_usd": assets_usd,
        "liabilities_idr": liabilities_idr,
        "liabilities_usd": liabilities_usd,
        "net_worth_idr": assets_idr - liabilities_idr,
        "net_worth_usd": assets_usd - liabilities_usd,
        "num_balances": row["num_balances"],
    }


def save_snapshot(db_path: str, snapshot: dict) -> bool:
    """
    Save net worth snapshot to database.

    Uses INSERT OR REPLACE to handle duplicates (idempotent).

    Args:
        db_path: Path to SQLite database
        snapshot: Dict with snapshot data

    Returns:
        True if inserted/updated, False if failed
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")

        # Use INSERT OR REPLACE to handle duplicates
        # This will update if snapshot_date already exists (UNIQUE constraint)
        conn.execute(
            """
            INSERT OR REPLACE INTO net_worth_history (
                snapshot_date,
                assets_idr,
                assets_usd,
                liabilities_idr,
                liabilities_usd,
                net_worth_idr,
                net_worth_usd,
                num_balances
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                snapshot["snapshot_date"],
                snapshot["assets_idr"],
                snapshot["assets_usd"],
                snapshot["liabilities_idr"],
                snapshot["liabilities_usd"],
                snapshot["net_worth_idr"],
                snapshot["net_worth_usd"],
                snapshot["num_balances"],
            ),
        )

        conn.commit()
        conn.close()

        return True

    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        return False


def snapshot_exists(db_path: str, snapshot_date: str) -> bool:
    """Check if a snapshot already exists for a given date."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT COUNT(*) FROM net_worth_history WHERE snapshot_date = ?",
        (snapshot_date,),
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def create_snapshot(db_path: str) -> bool:
    """
    Create a snapshot for today.

    Args:
        db_path: Path to SQLite database

    Returns:
        True if successful, False otherwise
    """
    # Get today's net worth summary
    summary = get_net_worth_summary(db_path)

    if summary is None:
        logging.warning("No data available")
        return False

    if summary["num_balances"] == 0:
        logging.warning("No balances found")
        return False

    snapshot_date = summary["snapshot_date"]

    # Check if updating existing snapshot
    exists = snapshot_exists(db_path, snapshot_date)
    action = "Updated" if exists else "Created"

    # Save snapshot
    if save_snapshot(db_path, summary):
        logging.info(
            f"✓ {action} snapshot for {snapshot_date}: "
            f"Assets=${summary['assets_usd']:,.2f}, "
            f"Liabilities=${summary['liabilities_usd']:,.2f}, "
            f"Net Worth=${summary['net_worth_usd']:,.2f} "
            f"({summary['num_balances']} balances)"
        )
        return True
    else:
        logging.error(f"✗ Failed to save snapshot for {snapshot_date}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create today's net worth snapshot")
    parser.add_argument(
        "database",
        nargs="?",
        default="data/portfolio.db",
        help="Path to SQLite database (default: data/portfolio.db)",
    )

    args = parser.parse_args()
    db_path = Path(args.database)

    # Setup paths
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".snapshot.lock"

    # Setup logging
    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info("Net Worth Snapshot - Starting")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")

    try:
        with LockFile(lock_file):
            logger.info("✓ Lock acquired")

            if not db_path.exists():
                logger.error(f"Database not found: {db_path}")
                sys.exit(1)

            if create_snapshot(str(db_path)):
                logger.info("=" * 70)
                logger.info("✓ Snapshot completed successfully")
                logger.info("=" * 70)
                sys.exit(0)
            else:
                logger.error("=" * 70)
                logger.error("✗ Snapshot failed")
                logger.error("=" * 70)
                sys.exit(1)

    except RuntimeError as e:
        logger.warning(str(e))
        sys.exit(2)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
