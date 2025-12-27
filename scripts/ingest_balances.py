#!/usr/bin/env python3
"""
Unified Balance Ingestion Script

Fetches balances from all sources (exchanges, wallets, fiat) and creates a single
unified snapshot. Can also run individual sources separately.

Usage:
    # Run all sources together (uses zero-balance logic)
    python scripts/ingest_balances.py

    # Run individual sources (skips zero-balance logic)
    python scripts/ingest_balances.py --sources exchanges
    python scripts/ingest_balances.py --sources wallets
    python scripts/ingest_balances.py --sources fiat

Requirements:
    - Exchange API keys in .env
    - RPC endpoints configured for wallets
    - Google Sheets access for fiat balances

Example cron (every 6 hours, all sources):
    0 */6 * * * cd /path && python scripts/ingest_balances.py >> logs/balances.log 2>&1
"""

import argparse
import fcntl
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from portfolio.blockchain import MultiChainAdapter, TokenBalance
from portfolio.exchanges import create_exchange

# Load environment
load_dotenv()


def setup_logging(log_dir: Path):
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_file = log_dir / f"balances_{datetime.now().strftime('%Y%m')}.log"
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


# ============================================================================
# EXCHANGE BALANCES
# ============================================================================


def fetch_exchange_balances(db_path: str) -> List[Dict]:
    """Fetch balances from crypto exchanges (Binance, OKX, Bitget)."""
    from portfolio.exchanges import Balance

    # Get exchange configs
    exchange_configs = {}

    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
        exchange_configs["Binance"] = {
            "exchange": "binance",
            "api_key": os.getenv("BINANCE_API_KEY"),
            "api_secret": os.getenv("BINANCE_API_SECRET"),
        }

    if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_API_PASSWORD"):
        exchange_configs["OKX"] = {
            "exchange": "okx",
            "api_key": os.getenv("OKX_API_KEY"),
            "api_secret": os.getenv("OKX_API_SECRET"),
            "password": os.getenv("OKX_API_PASSWORD"),
        }

    if (
        os.getenv("BITGET_API_KEY")
        and os.getenv("BITGET_API_SECRET")
        and os.getenv("BITGET_API_PASSWORD")
    ):
        exchange_configs["Bitget Evelyn"] = {
            "exchange": "bitget",
            "api_key": os.getenv("BITGET_API_KEY"),
            "api_secret": os.getenv("BITGET_API_SECRET"),
            "password": os.getenv("BITGET_API_PASSWORD"),
        }

    if not exchange_configs:
        logging.warning("No exchange API keys configured, skipping exchanges")
        return []

    # Get account mappings
    conn = sqlite3.connect(db_path)
    accounts = {
        row[0]: row[1]
        for row in conn.execute("SELECT name, id FROM accounts WHERE is_active = 1").fetchall()
    }
    conn.close()

    # Fetch balances
    all_balances = []

    for account_name, config in exchange_configs.items():
        if account_name not in accounts:
            logging.warning(f"Account '{account_name}' not found in database, skipping")
            continue

        account_id = accounts[account_name]
        logging.info(f"Fetching from {account_name}...")

        try:
            adapter = create_exchange(
                exchange_name=config["exchange"],
                api_key=config["api_key"],
                api_secret=config["api_secret"],
                password=config.get("password"),
                testnet=False,
            )

            balances = adapter.fetch_balances()
            logging.info(f"✓ {account_name}: Fetched {len(balances)} balances")

            for balance in balances:
                all_balances.append(
                    {
                        "account_id": account_id,
                        "account_name": account_name,
                        "currency": balance.currency,
                        "quantity": balance.total,
                        "source": "exchange",
                    }
                )

        except Exception as e:
            logging.error(f"✗ {account_name}: Failed to fetch balances - {e}")
            continue

    return all_balances


# ============================================================================
# WALLET BALANCES (On-Chain)
# ============================================================================


def fetch_wallet_balances(db_path: str) -> List[Dict]:
    """Fetch balances from on-chain wallets (EVM)."""

    # Get network configurations
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    network_configs = {}
    for row in conn.execute(
        """
        SELECT code, chain_id, rpc_endpoint
        FROM networks
        WHERE is_active = 1 AND is_evm = 1 AND rpc_endpoint IS NOT NULL
    """
    ):
        network_configs[row["code"]] = {
            "rpc_url": row["rpc_endpoint"],
            "chain_id": row["chain_id"],
        }

    if not network_configs:
        logging.warning("No network RPC endpoints configured, skipping wallets")
        conn.close()
        return []

    # Get wallet addresses
    wallet_accounts = {}
    for row in conn.execute(
        """
        SELECT account_id, network, address, account_name
        FROM active_wallet_addresses
        ORDER BY account_id, network
    """
    ):
        account_id = row["account_id"]
        if account_id not in wallet_accounts:
            wallet_accounts[account_id] = {"account_name": row["account_name"], "addresses": {}}
        wallet_accounts[account_id]["addresses"][row["network"]] = row["address"]

    if not wallet_accounts:
        logging.warning("No wallet addresses configured, skipping wallets")
        conn.close()
        return []

    # Get contract mappings
    contracts_by_network = {}
    native_decimals = {}
    native_currency_ids = {}

    for row in conn.execute(
        """
        SELECT network, contract_address, currency_id, decimals
        FROM blockchain_contracts
        WHERE is_active = 1 AND contract_address IS NOT NULL AND is_native = 0
    """
    ):
        network = row["network"]
        if network not in contracts_by_network:
            contracts_by_network[network] = {}
        contracts_by_network[network][row["contract_address"]] = (
            row["currency_id"],
            row["decimals"],
        )

    for row in conn.execute(
        """
        SELECT n.code as network, bc.currency_id, bc.decimals
        FROM networks n
        INNER JOIN blockchain_contracts bc ON bc.currency_id = n.native_currency_id
          AND bc.network = n.code AND bc.is_native = 1
        WHERE n.is_active = 1 AND n.is_evm = 1
    """
    ):
        native_decimals[row["network"]] = row["decimals"]
        native_currency_ids[row["network"]] = row["currency_id"]

    conn.close()

    # Transform contracts for adapter
    contracts_for_adapter = {}
    for network, contracts in contracts_by_network.items():
        contracts_for_adapter[network] = {
            addr: decimals for addr, (currency_id, decimals) in contracts.items()
        }

    # Initialize adapter
    try:
        adapter = MultiChainAdapter(network_configs)
    except Exception as e:
        logging.error(f"Failed to initialize blockchain adapter: {e}")
        return []

    # Fetch balances
    all_balances = []

    for account_id, wallet_info in wallet_accounts.items():
        account_name = wallet_info["account_name"]
        addresses = wallet_info["addresses"]

        logging.info(f"Fetching from {account_name}...")

        try:
            balances_by_network = adapter.fetch_wallet_balances(
                wallet_addresses=addresses,
                known_contracts=contracts_for_adapter,
                native_decimals=native_decimals,
            )

            for network, balances in balances_by_network.items():
                for balance in balances:
                    # Map to currency_id
                    if balance.is_native:
                        currency_id = native_currency_ids.get(network)
                    else:
                        contract_key = balance.contract_address.lower()
                        currency_id, _ = contracts_by_network[network].get(
                            contract_key, (None, None)
                        )

                    if currency_id:
                        all_balances.append(
                            {
                                "account_id": account_id,
                                "account_name": account_name,
                                "currency_id": currency_id,
                                "quantity": balance.balance,
                                "source": "wallet",
                            }
                        )

            logging.info(f"✓ {account_name}: Fetched balances from {len(addresses)} networks")

        except Exception as e:
            logging.error(f"✗ {account_name}: Failed to fetch balances - {e}")
            continue

    return all_balances


# ============================================================================
# FIAT BALANCES (Google Sheets)
# ============================================================================


def fetch_fiat_balances(db_path: str) -> List[Dict]:
    """Fetch fiat balances from Google Sheets."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
        from googleapiclient.discovery import build
    except ImportError:
        logging.warning("Google API libraries not installed, skipping fiat balances")
        return []

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_range = os.getenv("GOOGLE_SHEET_RANGE")

    if not all([creds_path, sheet_id, sheet_range]):
        logging.warning("Google Sheets not configured, skipping fiat balances")
        return []

    try:
        # Authenticate
        creds = ServiceAccountCredentials.from_service_account_file(
            creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )

        service = build("sheets", "v4", credentials=creds)
        sheet = service.spreadsheets()

        # Fetch data
        result = sheet.values().get(spreadsheetId=sheet_id, range=sheet_range).execute()
        values = result.get("values", [])

        if not values:
            logging.warning("No data found in Google Sheets")
            return []

        logging.info(f"Fetched {len(values)} rows from Google Sheets")

        # Get account and currency mappings
        conn = sqlite3.connect(db_path)
        accounts = {
            row[0]: row[1]
            for row in conn.execute("SELECT name, id FROM accounts WHERE is_active = 1").fetchall()
        }
        currencies = {
            row[0]: row[1] for row in conn.execute("SELECT code, id FROM currencies").fetchall()
        }
        conn.close()

        # Parse balances
        all_balances = []

        for row in values:
            if len(row) < 3:
                continue

            account_name = row[0].strip()
            currency_code = row[1].strip().upper()
            try:
                quantity = float(row[2])
            except ValueError:
                continue

            account_id = accounts.get(account_name)
            currency_id = currencies.get(currency_code)

            if account_id and currency_id and quantity != 0:
                all_balances.append(
                    {
                        "account_id": account_id,
                        "account_name": account_name,
                        "currency_id": currency_id,
                        "quantity": quantity,
                        "source": "fiat",
                    }
                )

        logging.info(f"✓ Parsed {len(all_balances)} fiat balances")
        return all_balances

    except Exception as e:
        logging.error(f"✗ Failed to fetch fiat balances: {e}")
        return []


# ============================================================================
# SHARED FUNCTIONS
# ============================================================================


def add_currency_ids(balances: List[Dict], db_path: str) -> List[Dict]:
    """Add currency_id to balances that only have currency code."""
    conn = sqlite3.connect(db_path)
    currencies = {
        row[0]: row[1] for row in conn.execute("SELECT code, id FROM currencies").fetchall()
    }
    conn.close()

    for balance in balances:
        if "currency_id" not in balance and "currency" in balance:
            currency_id = currencies.get(balance["currency"])
            if currency_id:
                balance["currency_id"] = currency_id
            else:
                logging.warning(f"Currency {balance['currency']} not found in database")
                balance["skip"] = True

    return balances


def calculate_values(balances: List[Dict], db_path: str) -> List[Dict]:
    """Calculate USD and IDR values using FX rates."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    fx_rates = {
        row["currency_id"]: row["rate"]
        for row in conn.execute("SELECT currency_id, rate FROM fx_rates").fetchall()
    }

    idr_currency_id = conn.execute("SELECT id FROM currencies WHERE code = 'IDR'").fetchone()
    idr_rate = fx_rates.get(idr_currency_id["id"]) if idr_currency_id else None

    conn.close()

    for balance in balances:
        if balance.get("skip"):
            continue

        currency_id = balance["currency_id"]
        rate_to_usd = fx_rates.get(currency_id)

        if not rate_to_usd:
            logging.warning(f"No FX rate for currency_id {currency_id}, skipping value calculation")
            balance["value_usd"] = None
            balance["value_idr"] = None
            balance["skip"] = True
            continue

        quantity = balance["quantity"]
        value_usd = quantity * rate_to_usd
        balance["value_usd"] = value_usd

        if idr_rate:
            balance["value_idr"] = value_usd / idr_rate
        else:
            balance["value_idr"] = None

        balance["skip"] = False

    return balances


def add_zero_balances_for_sold_assets(
    current_balances: List[Dict], db_path: str
) -> List[Dict]:
    """
    Add zero balances for previously held assets.

    ONLY call this when running ALL sources together!
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    current_holdings = {(bal["account_id"], bal["currency_id"]) for bal in current_balances}

    cursor = conn.execute(
        """
        SELECT DISTINCT account_id, currency_id
        FROM latest_balances
        WHERE quantity > 0
    """
    )

    historical_holdings = set(cursor.fetchall())
    conn.close()

    sold_holdings = historical_holdings - current_holdings

    if sold_holdings:
        logging.info(f"Found {len(sold_holdings)} previously held assets now at zero")

        for account_id, currency_id in sold_holdings:
            current_balances.append(
                {
                    "account_id": account_id,
                    "currency_id": currency_id,
                    "quantity": 0.0,
                }
            )

    return current_balances


def insert_balances(balances: List[Dict], db_path: str, timestamp: datetime) -> int:
    """Insert balance snapshot into database."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    inserted = 0

    try:
        for balance in balances:
            if balance.get("skip"):
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
    parser = argparse.ArgumentParser(description="Ingest balances from various sources")
    parser.add_argument(
        "--sources",
        choices=["all", "exchanges", "wallets", "fiat"],
        default="all",
        help="Which sources to fetch (default: all)",
    )
    parser.add_argument("database", nargs="?", default="data/portfolio.db", help="Database path")

    args = parser.parse_args()
    db_path = Path(args.database)

    # Setup
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".balances.lock"

    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info(f"Balance Ingestion - Starting (sources: {args.sources})")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")

    try:
        with LockFile(lock_file):
            logger.info("Lock acquired successfully")

            all_balances = []

            # Fetch from selected sources
            if args.sources in ["all", "exchanges"]:
                logger.info("\n--- Fetching Exchange Balances ---")
                exchange_balances = fetch_exchange_balances(str(db_path))
                all_balances.extend(exchange_balances)

            if args.sources in ["all", "wallets"]:
                logger.info("\n--- Fetching Wallet Balances ---")
                wallet_balances = fetch_wallet_balances(str(db_path))
                all_balances.extend(wallet_balances)

            if args.sources in ["all", "fiat"]:
                logger.info("\n--- Fetching Fiat Balances ---")
                fiat_balances = fetch_fiat_balances(str(db_path))
                all_balances.extend(fiat_balances)

            if not all_balances:
                logger.warning("No balances fetched from any source")
                sys.exit(0)

            logger.info(f"\nTotal balances fetched: {len(all_balances)}")

            # Add currency IDs for exchange balances (they only have currency code)
            logger.info("Mapping currency codes to IDs...")
            all_balances = add_currency_ids(all_balances, str(db_path))

            # Add zero balances ONLY when running all sources
            if args.sources == "all":
                logger.info("Checking for sold/transferred assets...")
                all_balances = add_zero_balances_for_sold_assets(all_balances, str(db_path))
            else:
                logger.info(
                    "Skipping zero-balance check (not running all sources - incomplete picture)"
                )

            # Calculate values
            logger.info("Calculating USD and IDR values...")
            all_balances = calculate_values(all_balances, str(db_path))

            # Insert snapshot
            snapshot_time = datetime.now()
            logger.info(f"Creating snapshot at {snapshot_time.isoformat()}")
            inserted = insert_balances(all_balances, str(db_path), snapshot_time)

            # Summary
            logger.info("=" * 70)
            logger.info(f"✓ Successfully imported {inserted} balances")
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
