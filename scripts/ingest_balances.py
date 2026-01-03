#!/usr/bin/env python3
"""
Unified Balance Ingestion Script

Fetches balances from all sources (exchanges, wallets, sheet) and creates a single
unified snapshot. Can also run individual sources separately.

Usage:
    # Run all sources together (uses zero-balance logic)
    python scripts/ingest_balances.py

    # Run individual sources (skips zero-balance logic)
    python scripts/ingest_balances.py --sources exchanges
    python scripts/ingest_balances.py --sources wallets
    python scripts/ingest_balances.py --sources sheet

Requirements:
    - Exchange API keys in .env
    - RPC endpoints configured for wallets
    - Google Sheets access for sheet balances

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

from portfolio.blockchain import MultiChainAdapter
from portfolio.exchanges import create_exchange

# Load environment
load_dotenv()


def setup_logging(log_dir: Path):
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    # Simple formatter without logger name to avoid duplication
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear existing handlers to prevent duplication
    logger.handlers.clear()

    # File handler
    log_file = log_dir / f"balances_{datetime.now().strftime('%Y%m')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Prevent propagation from imported module loggers
    for module in ["portfolio.blockchain", "portfolio.exchanges", "portfolio.tradingview"]:
        module_logger = logging.getLogger(module)
        module_logger.propagate = (
            True  # Let it propagate to root, but root only has one set of handlers
        )

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
        # Normalize address to lowercase for consistent lookups
        contracts_by_network[network][row["contract_address"].lower()] = (
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
# SHEET BALANCES (Google Sheets)
# ============================================================================


def fetch_sheet_balances(db_path: str) -> List[Dict]:
    """Fetch balances from Google Sheets (fiat and crypto)."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
        from googleapiclient.discovery import build
    except ImportError:
        logging.warning("Google API libraries not installed, skipping sheet balances")
        return []

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_range = os.getenv("GOOGLE_SHEET_RANGE")

    if not all([creds_path, sheet_id, sheet_range]):
        logging.warning("Google Sheets not configured, skipping sheet balances")
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

        # Parse balances - aggregate duplicates and track errors
        balance_dict = {}  # (account_id, currency_id) -> balance info
        duplicate_count = 0

        # Track issues for clean reporting
        missing_accounts = set()
        missing_currencies = set()
        invalid_amounts = []
        skipped_rows = []

        for idx, row in enumerate(values, start=2):  # start=2 because row 1 is header
            if len(row) < 3:
                skipped_rows.append(f"Row {idx}: Missing columns (has {len(row)}, needs 3)")
                continue

            account_name = row[0].strip()
            currency_code = row[1].strip().upper()
            amount_str = row[2].strip()

            # Validate amount
            try:
                quantity = float(amount_str.replace(",", ""))
            except ValueError:
                invalid_amounts.append(
                    f"Row {idx}: Invalid amount '{amount_str}' for {account_name}/{currency_code}"
                )
                continue

            # Check account exists
            account_id = accounts.get(account_name)
            if not account_id:
                missing_accounts.add(account_name)
                continue

            # Check currency exists
            currency_id = currencies.get(currency_code)
            if not currency_id:
                missing_currencies.add(currency_code)
                continue

            key = (account_id, currency_id)

            # Aggregate duplicates
            if key in balance_dict:
                old_quantity = balance_dict[key]["quantity"]
                new_quantity = old_quantity + quantity
                balance_dict[key]["quantity"] = new_quantity
                duplicate_count += 1
                logging.debug(
                    f"Row {idx}: Duplicate sheet entry for {account_name} / {currency_code} "
                    f"(aggregating: {old_quantity:,.2f} + {quantity:,.2f} = {new_quantity:,.2f})"
                )
            else:
                balance_dict[key] = {
                    "account_id": account_id,
                    "account_name": account_name,
                    "currency_id": currency_id,
                    "quantity": quantity,
                    "source": "sheet",
                }

        # Print clean summary of issues
        if missing_accounts or missing_currencies or invalid_amounts or skipped_rows:
            logging.warning("=" * 70)
            logging.warning("SHEET BALANCE ISSUES - ACTION REQUIRED")
            logging.warning("=" * 70)

            if missing_accounts:
                logging.warning(f"📋 Missing Accounts ({len(missing_accounts)}):")
                for account in sorted(missing_accounts):
                    logging.warning(f"  • {account}")
                logging.warning("  → Add via: scripts/bootstrap_accounts.py")

            if missing_currencies:
                logging.warning(f"💱 Missing Currencies ({len(missing_currencies)}):")
                for currency in sorted(missing_currencies):
                    logging.warning(f"  • {currency}")
                logging.warning("  → Add via: scripts/bootstrap_currencies.py")

            if invalid_amounts:
                logging.warning(f"⚠️  Invalid Amounts ({len(invalid_amounts)}):")
                for error in invalid_amounts:
                    logging.warning(f"  • {error}")
                logging.warning("  → Fix amounts in Google Sheets")

            if skipped_rows:
                logging.warning(f"⚠️  Skipped Rows ({len(skipped_rows)}):")
                for error in skipped_rows[:5]:  # Show first 5
                    logging.warning(f"  • {error}")
                if len(skipped_rows) > 5:
                    logging.warning(f"  ... and {len(skipped_rows) - 5} more")
                logging.warning("  → Fix formatting in Google Sheets")

            logging.warning("=" * 70)

        if duplicate_count > 0:
            logging.info(f"✓ Aggregated {duplicate_count} duplicate entries")

        all_balances = list(balance_dict.values())
        logging.info(f"✓ Parsed {len(all_balances)} sheet balances")
        return all_balances

    except Exception as e:
        logging.error(f"✗ Failed to fetch sheet balances: {e}")
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

    # Track missing currencies from exchanges
    missing_currencies = set()

    for balance in balances:
        if "currency_id" not in balance and "currency" in balance:
            currency_id = currencies.get(balance["currency"])
            if currency_id:
                balance["currency_id"] = currency_id
            else:
                missing_currencies.add(balance["currency"])
                balance["skip"] = True

    # Print clean summary
    if missing_currencies:
        logging.warning("=" * 70)
        logging.warning("EXCHANGE BALANCE ISSUES - ACTION REQUIRED")
        logging.warning("=" * 70)
        logging.warning(f"💱 Missing Currencies ({len(missing_currencies)}):")
        for currency in sorted(missing_currencies):
            logging.warning(f"  • {currency}")
        logging.warning("  → Add via: python scripts/bootstrap_currencies.py")
        logging.warning("=" * 70)

    return balances


def calculate_values(balances: List[Dict], db_path: str) -> List[Dict]:
    """Calculate USD and IDR values using FX rates."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    fx_rates = {
        row["currency_id"]: row["rate"]
        for row in conn.execute("SELECT currency_id, rate FROM fx_rates").fetchall()
    }

    # Get currency code lookup for better error messages
    currency_codes = {
        row["id"]: row["code"] for row in conn.execute("SELECT id, code FROM currencies").fetchall()
    }

    idr_currency_id = conn.execute("SELECT id FROM currencies WHERE code = 'IDR'").fetchone()
    idr_rate = fx_rates.get(idr_currency_id["id"]) if idr_currency_id else None

    conn.close()

    # Track missing FX rates
    missing_fx_rates = set()

    for balance in balances:
        if balance.get("skip"):
            continue

        currency_id = balance["currency_id"]
        rate_to_usd = fx_rates.get(currency_id)

        if not rate_to_usd:
            currency_code = currency_codes.get(currency_id, f"ID:{currency_id}")
            missing_fx_rates.add(currency_code)
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

    # Print clean summary of missing FX rates
    if missing_fx_rates:
        logging.warning("=" * 70)
        logging.warning("MISSING FX RATES - ACTION REQUIRED")
        logging.warning("=" * 70)
        logging.warning(f"💱 Currencies without FX rates ({len(missing_fx_rates)}):")
        for currency in sorted(missing_fx_rates):
            logging.warning(f"  • {currency}")
        logging.warning("  → Add rates via: python scripts/ingest_fx_rates.py")
        logging.warning("  → Or add symbol mappings first: python scripts/bootstrap_symbol_mappings.py")
        logging.warning("=" * 70)

    return balances


def add_zero_balances_for_sold_assets(current_balances: List[Dict], db_path: str) -> List[Dict]:
    """
    Add zero balances for previously held assets.

    ONLY call this when running ALL sources together!
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Filter out balances that should be skipped (missing currency_id, etc.)
    valid_balances = [bal for bal in current_balances if not bal.get("skip")]

    current_holdings = {(bal["account_id"], bal["currency_id"]) for bal in valid_balances}

    cursor = conn.execute(
        """
        SELECT DISTINCT account_id, currency_id
        FROM latest_balances
        WHERE quantity > 0
    """
    )

    historical_holdings = {(row["account_id"], row["currency_id"]) for row in cursor.fetchall()}

    sold_holdings = historical_holdings - current_holdings

    if sold_holdings:
        # Get account and currency names for logging
        cursor = conn.execute(
            """
            SELECT id, name FROM accounts
        """
        )
        account_names = {row["id"]: row["name"] for row in cursor.fetchall()}

        cursor = conn.execute(
            """
            SELECT id, code FROM currencies
        """
        )
        currency_codes = {row["id"]: row["code"] for row in cursor.fetchall()}

        # Log zeroed holdings
        logging.warning("=" * 70)
        logging.warning("ZERO-BALANCE TRACKING")
        logging.warning("=" * 70)
        logging.warning(f"🔄 Recording {len(sold_holdings)} asset(s) now at zero:")

        for account_id, currency_id in sorted(sold_holdings):
            account_name = account_names.get(account_id, f"Account#{account_id}")
            currency_code = currency_codes.get(currency_id, f"Currency#{currency_id}")
            logging.warning(f"  • {account_name} / {currency_code} → 0.00")

        logging.warning("=" * 70)

        for account_id, currency_id in sold_holdings:
            current_balances.append(
                {
                    "account_id": account_id,
                    "currency_id": currency_id,
                    "quantity": 0.0,
                }
            )

    conn.close()

    return current_balances


def insert_balances(balances: List[Dict], db_path: str, timestamp: datetime) -> int:
    """Insert balance snapshot into database."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Deduplicate: aggregate balances by (account_id, currency_id)
    balance_dict = {}

    for balance in balances:
        if balance.get("skip"):
            continue

        key = (balance["account_id"], balance["currency_id"])

        if key in balance_dict:
            # Duplicate - sum quantities and recalculate values
            old_qty = balance_dict[key]["quantity"]
            new_qty = old_qty + balance["quantity"]
            balance_dict[key]["quantity"] = new_qty

            # Recalculate values (assuming value_usd per unit is same)
            if balance.get("value_usd") and old_qty != 0:
                rate = balance_dict[key]["value_usd"] / old_qty
                balance_dict[key]["value_usd"] = new_qty * rate
                if balance.get("value_idr"):
                    idr_rate = balance_dict[key]["value_idr"] / old_qty
                    balance_dict[key]["value_idr"] = new_qty * idr_rate
        else:
            balance_dict[key] = balance.copy()

    inserted = 0

    try:
        for balance in balance_dict.values():
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
        choices=["all", "exchanges", "wallets", "sheet"],
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
                logger.info("--- Fetching Exchange Balances ---")
                exchange_balances = fetch_exchange_balances(str(db_path))
                all_balances.extend(exchange_balances)

            if args.sources in ["all", "wallets"]:
                logger.info("--- Fetching Wallet Balances ---")
                wallet_balances = fetch_wallet_balances(str(db_path))
                all_balances.extend(wallet_balances)

            if args.sources in ["all", "sheet"]:
                logger.info("--- Fetching Sheet Balances ---")
                sheet_balances = fetch_sheet_balances(str(db_path))
                all_balances.extend(sheet_balances)

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
