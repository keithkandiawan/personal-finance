#!/usr/bin/env python3
"""
Fiat Balance Ingestion Script

Reads current fiat balances from Google Sheets and creates a snapshot in the database.
Designed to run via cron with proper locking and logging.

Usage:
    python scripts/ingest_fiat_balances.py [database_path]

    If no database_path is provided, defaults to 'data/portfolio.db'

Requirements:
    - Google Sheets API credentials (google_credentials.json)
    - .env file with GOOGLE_SHEET_ID and GOOGLE_SHEET_RANGE
    - Service account has Viewer access to the sheet

Example cron (daily at 8 AM):
    0 8 * * * cd /path/to/personal-finance && python scripts/ingest_fiat_balances.py >> logs/fiat_balances.log 2>&1
"""

import fcntl
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Environment variables
from dotenv import load_dotenv

# Google Sheets
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# Load environment variables
load_dotenv()


def setup_logging(log_dir: Path):
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_file = log_dir / f"fiat_balances_{datetime.now().strftime('%Y%m')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
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
            raise RuntimeError(f"Another instance is already running (lock file: {self.lock_path})")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            try:
                self.lock_path.unlink()
            except:
                pass


def read_google_sheet(credentials_path: str, sheet_id: str, range_name: str) -> List[List[str]]:
    """
    Read data from Google Sheets.

    Args:
        credentials_path: Path to service account JSON
        sheet_id: Google Sheets ID
        range_name: Range to read (e.g., 'Fiat Balances!A2:C')

    Returns:
        List of rows, each row is a list of values
    """
    try:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )

        service = build("sheets", "v4", credentials=credentials)
        sheet = service.spreadsheets()

        result = sheet.values().get(spreadsheetId=sheet_id, range=range_name).execute()

        values = result.get("values", [])
        logging.info(f"Read {len(values)} rows from Google Sheets")
        return values

    except HttpError as e:
        logging.error(f"Google Sheets API error: {e}")
        raise
    except Exception as e:
        logging.error(f"Error reading Google Sheets: {e}")
        raise


def validate_and_prepare_balances(rows: List[List[str]], db_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Validate sheet data and prepare balance records.

    Expected columns: Account | Currency | Amount

    Automatically aggregates duplicate account/currency combinations.

    Args:
        rows: Raw rows from Google Sheets
        db_path: Path to database

    Returns:
        Tuple of (validated balance list, error list)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get valid accounts and currencies
    accounts = {
        row["name"]: row["id"]
        for row in conn.execute("SELECT id, name FROM accounts WHERE is_active = 1").fetchall()
    }
    currencies = {
        row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM currencies").fetchall()
    }

    # Use dict to aggregate duplicates: (account_id, currency_id) -> balance_info
    balance_dict = {}
    errors = []
    duplicate_count = 0

    for idx, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        if len(row) < 3:
            errors.append(f"Row {idx}: Missing columns (expected 3, got {len(row)})")
            continue

        account_name, currency_code, amount_str = row[0], row[1], row[2]

        # Validate account
        if account_name not in accounts:
            errors.append(f"Row {idx}: Unknown account '{account_name}'")
            continue

        # Validate currency
        if currency_code not in currencies:
            errors.append(f"Row {idx}: Unknown currency '{currency_code}'")
            continue

        # Validate amount
        try:
            amount = float(amount_str.replace(",", ""))
        except ValueError:
            errors.append(f"Row {idx}: Invalid amount '{amount_str}'")
            continue

        account_id = accounts[account_name]
        currency_id = currencies[currency_code]
        key = (account_id, currency_id)

        # Aggregate duplicates
        if key in balance_dict:
            # Duplicate found - sum the amounts
            old_amount = balance_dict[key]["quantity"]
            new_amount = old_amount + amount
            balance_dict[key]["quantity"] = new_amount
            duplicate_count += 1
            logging.warning(
                f"Row {idx}: Duplicate entry for {account_name} / {currency_code} "
                f"(aggregating: {old_amount:,.2f} + {amount:,.2f} = {new_amount:,.2f})"
            )
        else:
            balance_dict[key] = {
                "account_id": account_id,
                "account_name": account_name,
                "currency_id": currency_id,
                "currency_code": currency_code,
                "quantity": amount,
            }

    conn.close()

    if errors:
        logging.warning(f"Found {len(errors)} validation errors:")
        for error in errors[:10]:  # Show first 10
            logging.warning(f"  • {error}")

    if duplicate_count > 0:
        logging.warning(f"Aggregated {duplicate_count} duplicate entries")

    balances = list(balance_dict.values())
    logging.info(f"Validated {len(balances)} unique balance records")
    return balances, errors


def calculate_values(balances: List[Dict], db_path: str) -> List[Dict]:
    """
    Calculate USD and IDR values using current FX rates.

    Args:
        balances: List of balance dictionaries
        db_path: Path to database

    Returns:
        Updated balances with value_usd and value_idr
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all FX rates
    fx_rates = {
        row["currency_id"]: row["rate"]
        for row in conn.execute("SELECT currency_id, rate FROM fx_rates").fetchall()
    }

    # Get IDR rate for conversion
    idr_currency_id = conn.execute("SELECT id FROM currencies WHERE code = 'IDR'").fetchone()
    idr_rate = fx_rates.get(idr_currency_id["id"]) if idr_currency_id else None

    conn.close()

    for balance in balances:
        currency_id = balance["currency_id"]
        quantity = balance["quantity"]

        # Get rate to USD
        rate_to_usd = fx_rates.get(currency_id)

        if rate_to_usd is None:
            logging.warning(
                f"Missing FX rate for {balance['currency_code']}, skipping value calculation"
            )
            balance["value_usd"] = None
            balance["value_idr"] = None
            continue

        # Calculate USD value
        value_usd = quantity * rate_to_usd
        balance["value_usd"] = value_usd

        # Calculate IDR value
        if idr_rate:
            value_idr = value_usd / idr_rate
            balance["value_idr"] = value_idr
        else:
            logging.warning("Missing IDR FX rate, cannot calculate value_idr")
            balance["value_idr"] = None

    return balances


def add_zero_balances_for_sold_assets(current_balances: List[Dict], db_path: str) -> List[Dict]:
    """
    Add explicit zero-balance records for currencies that were previously held
    but are no longer in the current snapshot.

    This ensures the latest_balances view doesn't show stale balances.

    Args:
        current_balances: List of current balance dictionaries
        db_path: Database path

    Returns:
        Updated balance list with zeros for missing currencies
    """
    conn = sqlite3.connect(db_path)

    # Get current snapshot as a set of (account_id, currency_id) tuples
    current_holdings = {(bal["account_id"], bal["currency_id"]) for bal in current_balances}

    # Get all historical holdings from latest_balances view
    cursor = conn.execute("""
        SELECT DISTINCT account_id, currency_id, currency_code
        FROM latest_balances
        WHERE quantity != 0
    """)

    historical_holdings = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
    conn.close()

    # Find holdings that were in history but not in current snapshot
    sold_holdings = set(historical_holdings.keys()) - current_holdings

    if sold_holdings:
        logging.info(f"Found {len(sold_holdings)} previously held currencies now at zero")

        # Add zero balance records
        for account_id, currency_id in sold_holdings:
            currency_code = historical_holdings[(account_id, currency_id)]
            current_balances.append(
                {
                    "account_id": account_id,
                    "currency_id": currency_id,
                    "currency_code": currency_code,
                    "quantity": 0.0,
                    "value_usd": 0.0,
                    "value_idr": 0.0,
                }
            )
            logging.info(f"  Adding zero balance: account_id={account_id}, {currency_code}")

    return current_balances


def insert_balances(balances: List[Dict], db_path: str, timestamp: datetime) -> int:
    """
    Insert balance snapshot into database.

    Args:
        balances: List of balance dictionaries
        db_path: Path to database
        timestamp: Snapshot timestamp

    Returns:
        Number of inserted records
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    inserted = 0

    try:
        for balance in balances:
            # Skip if missing values
            if balance["value_usd"] is None:
                continue

            conn.execute(
                """
                INSERT INTO balances (
                    timestamp, account_id, currency_id,
                    quantity, value_idr, value_usd
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    timestamp.isoformat(),
                    balance["account_id"],
                    balance["currency_id"],
                    balance["quantity"],
                    balance["value_idr"],
                    balance["value_usd"],
                ),
            )
            inserted += 1

        conn.commit()
        logging.info(f"Inserted {inserted} balance records")

    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

    return inserted


def main():
    """Main entry point."""
    # Parse arguments
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/portfolio.db")

    # Setup paths
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".fiat_balances.lock"

    # Setup logging
    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info("Fiat Balance Ingestion - Starting")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")

    # Get configuration from environment
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_range = os.getenv("GOOGLE_SHEET_RANGE", "Fiat Balances!A2:C")

    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID not set in environment")
        logger.error("Create a .env file with GOOGLE_SHEET_ID=your-sheet-id")
        sys.exit(1)

    logger.info(f"Sheet ID: {sheet_id}")
    logger.info(f"Sheet Range: {sheet_range}")

    try:
        with LockFile(lock_file):
            logger.info("Lock acquired successfully")

            # Read from Google Sheets
            logger.info("Reading from Google Sheets...")
            rows = read_google_sheet(credentials_path, sheet_id, sheet_range)

            if not rows:
                logger.warning("No data found in Google Sheets")
                sys.exit(0)

            # Validate and prepare
            logger.info("Validating data...")
            balances, errors = validate_and_prepare_balances(rows, str(db_path))

            if not balances:
                logger.error("No valid balances to import")
                sys.exit(1)

            # Calculate values
            logger.info("Calculating USD and IDR values...")
            balances = calculate_values(balances, str(db_path))

            # Insert snapshot
            snapshot_time = datetime.now()
            logger.info(f"Creating snapshot at {snapshot_time.isoformat()}")
            inserted = insert_balances(balances, str(db_path), snapshot_time)

            # Summary
            logger.info("=" * 70)
            logger.info(f"✓ Successfully imported {inserted} fiat balances")
            if errors:
                logger.warning(f"⚠ {len(errors)} rows had validation errors")
            logger.info("=" * 70)
            sys.exit(0)

    except RuntimeError as e:
        logger.warning(str(e))
        sys.exit(2)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
