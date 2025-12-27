#!/usr/bin/env python3
"""
Crypto Balance Ingestion Script

Fetches current crypto balances from configured exchanges and creates snapshots.
Supports: Binance, OKX, Bitget

Usage:
    python scripts/ingest_crypto_balances.py [database_path]

Requirements:
    - Exchange API keys in .env file
    - Accounts must exist in database with matching names

Example cron (every 4 hours):
    0 */4 * * * cd /path/to/personal-finance && python scripts/ingest_crypto_balances.py >> logs/crypto_balances.log 2>&1
"""

import sys
import sqlite3
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import fcntl

from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from portfolio.exchanges import create_exchange, Balance


# Load environment
load_dotenv()


def setup_logging(log_dir: Path):
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    log_file = log_dir / f"crypto_balances_{datetime.now().strftime('%Y%m')}.log"
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
        self.lock_file = open(self.lock_path, 'w')
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


def get_exchange_config() -> Dict:
    """
    Load exchange API configurations from environment.

    Returns:
        Dictionary of exchange configs
    """
    exchanges = {}

    # Binance
    if os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_API_SECRET'):
        exchanges['Binance'] = {
            'exchange': 'binance',
            'api_key': os.getenv('BINANCE_API_KEY'),
            'api_secret': os.getenv('BINANCE_API_SECRET'),
        }

    # OKX
    if os.getenv('OKX_API_KEY') and os.getenv('OKX_API_SECRET') and os.getenv('OKX_API_PASSWORD'):
        exchanges['OKX'] = {
            'exchange': 'okx',
            'api_key': os.getenv('OKX_API_KEY'),
            'api_secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_API_PASSWORD'),
        }

    # Bitget
    if os.getenv('BITGET_API_KEY') and os.getenv('BITGET_API_SECRET') and os.getenv('BITGET_API_PASSWORD'):
        exchanges['Bitget Evelyn'] = {
            'exchange': 'bitget',
            'api_key': os.getenv('BITGET_API_KEY'),
            'api_secret': os.getenv('BITGET_API_SECRET'),
            'password': os.getenv('BITGET_API_PASSWORD'),
        }

    return exchanges


def fetch_exchange_balances(account_name: str, config: Dict) -> List[Balance]:
    """
    Fetch balances from a single exchange.

    Args:
        account_name: Account name in database
        config: Exchange configuration

    Returns:
        List of Balance objects
    """
    try:
        adapter = create_exchange(
            exchange_name=config['exchange'],
            api_key=config['api_key'],
            api_secret=config['api_secret'],
            password=config.get('password'),
            testnet=False
        )

        balances = adapter.fetch_balances()
        logging.info(f"✓ {account_name}: Fetched {len(balances)} balances")
        return balances

    except Exception as e:
        logging.error(f"✗ {account_name}: Failed to fetch balances - {e}")
        return []


def calculate_values(
    balances: List[Dict],
    db_path: str
) -> List[Dict]:
    """
    Calculate USD and IDR values using FX rates.

    Args:
        balances: List of balance dictionaries
        db_path: Database path

    Returns:
        Balances with calculated values
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get FX rates
    fx_rates = {row['currency_id']: row['rate'] for row in
                conn.execute("SELECT currency_id, rate FROM fx_rates").fetchall()}

    # Get IDR rate
    idr_currency_id = conn.execute(
        "SELECT id FROM currencies WHERE code = 'IDR'"
    ).fetchone()
    idr_rate = fx_rates.get(idr_currency_id['id']) if idr_currency_id else None

    # Get currency IDs
    currencies = {row['code']: row['id'] for row in
                  conn.execute("SELECT id, code FROM currencies").fetchall()}

    conn.close()

    for balance in balances:
        currency_code = balance['currency']
        currency_id = currencies.get(currency_code)

        if not currency_id:
            logging.warning(f"Currency {currency_code} not in database, skipping")
            balance['skip'] = True
            continue

        balance['currency_id'] = currency_id

        # Get FX rate
        rate_to_usd = fx_rates.get(currency_id)
        if not rate_to_usd:
            logging.warning(f"No FX rate for {currency_code}, skipping value calculation")
            balance['value_usd'] = None
            balance['value_idr'] = None
            balance['skip'] = True
            continue

        # Calculate values
        quantity = balance['quantity']
        value_usd = quantity * rate_to_usd
        balance['value_usd'] = value_usd

        if idr_rate:
            balance['value_idr'] = value_usd / idr_rate
        else:
            balance['value_idr'] = None

        balance['skip'] = False

    return balances


def insert_balances(
    balances: List[Dict],
    db_path: str,
    timestamp: datetime
) -> int:
    """Insert balance snapshot into database."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    inserted = 0

    try:
        for balance in balances:
            if balance.get('skip'):
                continue

            conn.execute("""
                INSERT INTO balances (
                    timestamp, account_id, currency_id,
                    quantity, value_idr, value_usd
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                timestamp.isoformat(),
                balance['account_id'],
                balance['currency_id'],
                balance['quantity'],
                balance['value_idr'],
                balance['value_usd']
            ))
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

    # Setup
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".crypto_balances.lock"

    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info("Crypto Balance Ingestion - Starting")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")

    try:
        with LockFile(lock_file):
            logger.info("Lock acquired successfully")

            # Get exchange configs
            exchange_configs = get_exchange_config()

            if not exchange_configs:
                logger.error("No exchange API keys configured")
                logger.error("Set API keys in .env file")
                sys.exit(1)

            logger.info(f"Configured exchanges: {', '.join(exchange_configs.keys())}")

            # Get account IDs from database
            conn = sqlite3.connect(db_path)
            accounts = {row[0]: row[1] for row in
                       conn.execute("SELECT name, id FROM accounts WHERE is_active = 1").fetchall()}
            conn.close()

            # Fetch balances from all exchanges
            all_balances = []

            for account_name, config in exchange_configs.items():
                if account_name not in accounts:
                    logger.warning(f"Account '{account_name}' not found in database, skipping")
                    continue

                account_id = accounts[account_name]
                logger.info(f"Fetching from {account_name}...")

                balances = fetch_exchange_balances(account_name, config)

                for balance in balances:
                    all_balances.append({
                        'account_id': account_id,
                        'account_name': account_name,
                        'currency': balance.currency,
                        'quantity': balance.total,
                    })

            if not all_balances:
                logger.warning("No balances fetched from any exchange")
                sys.exit(0)

            logger.info(f"Total balances fetched: {len(all_balances)}")

            # Calculate values
            logger.info("Calculating USD and IDR values...")
            all_balances = calculate_values(all_balances, str(db_path))

            # Insert snapshot
            snapshot_time = datetime.now()
            logger.info(f"Creating snapshot at {snapshot_time.isoformat()}")
            inserted = insert_balances(all_balances, str(db_path), snapshot_time)

            # Summary
            logger.info("=" * 70)
            logger.info(f"✓ Successfully imported {inserted} crypto balances")
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
