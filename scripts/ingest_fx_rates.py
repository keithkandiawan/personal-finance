#!/usr/bin/env python3
"""
FX Rate Ingestion Script

Fetches current FX rates from TradingView and updates the database.
Designed to run via cron with proper locking and logging.

Usage:
    python scripts/ingest_fx_rates.py [database_path]

    If no database_path is provided, defaults to 'data/portfolio.db'

Example cron (daily at 9 AM):
    0 9 * * * cd /path/to/personal-finance && python scripts/ingest_fx_rates.py >> logs/fx_rates.log 2>&1
"""

import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
import fcntl
import os

# Add src directory to path to import portfolio package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from portfolio.tradingview import fetch_and_update_prices, check_stale_rates


# Configure logging
def setup_logging(log_dir: Path):
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File handler (with rotation)
    log_file = log_dir / f"fx_rates_{datetime.now().strftime('%Y%m')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


class LockFile:
    """Context manager for file-based locking to prevent concurrent runs."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock_file = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self.lock_path, 'w')

        try:
            # Non-blocking lock
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
            # Clean up lock file
            try:
                self.lock_path.unlink()
            except:
                pass


def validate_database(db_path: Path) -> bool:
    """
    Validate that the database exists and has the required tables.

    Args:
        db_path: Path to the database file

    Returns:
        True if valid, False otherwise
    """
    if not db_path.exists():
        logging.error(f"Database not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('currencies', 'symbol_mappings', 'fx_rates')"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        required_tables = {'currencies', 'symbol_mappings', 'fx_rates'}
        if not required_tables.issubset(set(tables)):
            missing = required_tables - set(tables)
            logging.error(f"Missing required tables: {missing}")
            return False

        return True

    except sqlite3.Error as e:
        logging.error(f"Database validation error: {e}")
        return False


def main():
    """Main entry point."""
    # Parse arguments
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/portfolio.db")

    # Setup paths
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".fx_rates.lock"

    # Setup logging
    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info("FX Rate Ingestion - Starting")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")
    logger.info(f"Lock file: {lock_file}")

    try:
        # Acquire lock
        with LockFile(lock_file):
            logger.info("Lock acquired successfully")

            # Validate database
            if not validate_database(db_path):
                logger.error("Database validation failed")
                sys.exit(1)

            # Check for stale rates before update
            stale_before = check_stale_rates(str(db_path), hours=24)
            if stale_before:
                logger.warning(f"Found {len(stale_before)} stale rates (>24h old)")
                for rate in stale_before[:5]:  # Show first 5
                    logger.warning(f"  • {rate['currency_code']}: {rate['hours_old']}h old")

            # Fetch and update prices
            logger.info("Fetching prices from TradingView...")
            updated_count = fetch_and_update_prices(str(db_path))

            if updated_count > 0:
                logger.info(f"✓ Successfully updated {updated_count} FX rates")

                # Check for remaining stale rates
                stale_after = check_stale_rates(str(db_path), hours=24)
                if stale_after:
                    logger.warning(f"Still have {len(stale_after)} stale rates:")
                    for rate in stale_after:
                        logger.warning(
                            f"  • {rate['currency_code']}: {rate['hours_old']}h old "
                            f"(last update: {rate['updated_at']})"
                        )
                else:
                    logger.info("✓ All FX rates are fresh (<24h old)")

                # Summary
                logger.info("=" * 70)
                logger.info("FX Rate Ingestion - Success")
                logger.info("=" * 70)
                sys.exit(0)
            else:
                logger.error("✗ No FX rates were updated")
                logger.error("=" * 70)
                logger.error("FX Rate Ingestion - Failed")
                logger.error("=" * 70)
                sys.exit(1)

    except RuntimeError as e:
        # Lock file error (another instance running)
        logger.warning(str(e))
        logger.info("Exiting - another instance is already running")
        sys.exit(2)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        logger.error("=" * 70)
        logger.error("FX Rate Ingestion - Failed with error")
        logger.error("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
