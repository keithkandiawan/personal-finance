#!/usr/bin/env python3
"""
On-Chain Balance Ingestion Script

Fetches current balances from EVM wallets and creates snapshots.
Supports: Ethereum, Polygon, BSC, Arbitrum, Optimism, Base

Usage:
    python scripts/ingest_onchain_balances.py [database_path]

Requirements:
    - RPC endpoints configured in networks table
    - Wallet addresses in wallet_addresses table
    - web3 library installed

Example cron (every 6 hours):
    0 */6 * * * cd /path/to/personal-finance && python scripts/ingest_onchain_balances.py >> logs/onchain_balances.log 2>&1
"""

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

# Load environment
load_dotenv()


def setup_logging(log_dir: Path):
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_file = log_dir / f"onchain_balances_{datetime.now().strftime('%Y%m')}.log"
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


def get_network_configs(db_path: str) -> Dict[str, Dict]:
    """
    Load network configurations from database.

    Returns:
        Dictionary of network configs with RPC URLs and chain IDs
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    networks = {}
    for row in conn.execute(
        """
        SELECT code, chain_id, rpc_endpoint
        FROM networks
        WHERE is_active = 1 AND is_evm = 1 AND rpc_endpoint IS NOT NULL
    """
    ):
        networks[row["code"]] = {
            "rpc_url": row["rpc_endpoint"],
            "chain_id": row["chain_id"],
        }

    conn.close()
    return networks


def get_wallet_addresses(db_path: str) -> Dict[int, Dict[str, str]]:
    """
    Load wallet addresses from database.

    Returns:
        Dictionary of account_id -> {network: address}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    wallet_addresses = {}
    for row in conn.execute(
        """
        SELECT account_id, network, address, account_name
        FROM active_wallet_addresses
        ORDER BY account_id, network
    """
    ):
        account_id = row["account_id"]
        if account_id not in wallet_addresses:
            wallet_addresses[account_id] = {"account_name": row["account_name"], "addresses": {}}

        wallet_addresses[account_id]["addresses"][row["network"]] = row["address"]

    conn.close()
    return wallet_addresses


def get_contract_mappings(db_path: str) -> Tuple[Dict, Dict, Dict]:
    """
    Load contract to currency mappings from blockchain_contracts table.

    Returns:
        Tuple of:
        - contracts_by_network: Dict[network, Dict[contract_address, (currency_id, decimals)]]
        - native_decimals: Dict[network, decimals]
        - native_currency_ids: Dict[network, currency_id]
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    contracts_by_network = {}
    native_decimals = {}
    native_currency_ids = {}

    # Get ERC-20 contracts
    for row in conn.execute(
        """
        SELECT network, contract_address, currency_id, decimals
        FROM blockchain_contracts
        WHERE is_active = 1
          AND contract_address IS NOT NULL
          AND is_native = 0
        ORDER BY network
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

    # Get native token info
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
    return contracts_by_network, native_decimals, native_currency_ids


def calculate_values(balances: List[Dict], db_path: str) -> List[Dict]:
    """
    Calculate USD and IDR values using FX rates.

    Args:
        balances: List of balance dictionaries (already have currency_id)
        db_path: Database path

    Returns:
        Balances with calculated values
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get FX rates
    fx_rates = {
        row["currency_id"]: row["rate"]
        for row in conn.execute("SELECT currency_id, rate FROM fx_rates").fetchall()
    }

    # Get IDR rate
    idr_currency_id = conn.execute("SELECT id FROM currencies WHERE code = 'IDR'").fetchone()
    idr_rate = fx_rates.get(idr_currency_id["id"]) if idr_currency_id else None

    conn.close()

    for balance in balances:
        currency_id = balance["currency_id"]

        # Get FX rate
        rate_to_usd = fx_rates.get(currency_id)
        if not rate_to_usd:
            # Get currency code for logging
            logging.warning(f"No FX rate for currency_id {currency_id}, skipping value calculation")
            balance["value_usd"] = None
            balance["value_idr"] = None
            balance["skip"] = True
            continue

        # Calculate values
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
    current_balances: List[Dict], wallet_accounts: Dict[int, Dict], db_path: str
) -> List[Dict]:
    """
    Add explicit zero-balance records for currencies that were previously held
    but are no longer in the current snapshot (i.e., transferred out or sold).

    This ensures the latest_balances view doesn't show stale balances.

    Args:
        current_balances: List of current balance dictionaries
        wallet_accounts: Dict of wallet account info
        db_path: Database path

    Returns:
        Updated balance list with zeros for missing currencies
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get current snapshot as a set of (account_id, currency_id) tuples
    current_holdings = {(bal["account_id"], bal["currency_id"]) for bal in current_balances}

    # Get all historical holdings for wallet accounts
    account_ids = tuple(wallet_accounts.keys())
    cursor = conn.execute(
        f"""
        SELECT DISTINCT account_id, currency_id
        FROM latest_balances
        WHERE account_id IN ({",".join("?" * len(account_ids))})
          AND quantity > 0
    """,
        account_ids,
    )

    historical_holdings = set(cursor.fetchall())
    conn.close()

    # Find currencies that were held before but not in current snapshot
    sold_holdings = historical_holdings - current_holdings

    if sold_holdings:
        logging.info(f"Found {len(sold_holdings)} previously held tokens now at zero")

        for account_id, currency_id in sold_holdings:
            account_name = wallet_accounts.get(account_id, {}).get("account_name", "Unknown")
            current_balances.append(
                {
                    "account_id": account_id,
                    "account_name": account_name,
                    "currency_id": currency_id,
                    "quantity": 0.0,
                }
            )
            logging.info(f"  Adding zero balance: {account_name} - currency_id {currency_id}")

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
    # Parse arguments
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/portfolio.db")

    # Setup
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".onchain_balances.lock"

    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info("On-Chain Balance Ingestion - Starting")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")

    try:
        with LockFile(lock_file):
            logger.info("Lock acquired successfully")

            # Get network configurations
            network_configs = get_network_configs(str(db_path))

            if not network_configs:
                logger.error("No network RPC endpoints configured")
                logger.error("Run: python scripts/bootstrap_rpc_endpoints.py")
                sys.exit(1)

            logger.info(f"Configured networks: {', '.join(network_configs.keys())}")

            # Get wallet addresses
            wallet_accounts = get_wallet_addresses(str(db_path))

            if not wallet_accounts:
                logger.error("No wallet addresses configured")
                logger.error("Run: python scripts/add_wallet_addresses.py")
                sys.exit(1)

            logger.info(
                f"Configured wallets: {', '.join([v['account_name'] for v in wallet_accounts.values()])}"
            )

            # Get contract mappings
            contracts_by_network, native_decimals, native_currency_ids = get_contract_mappings(
                str(db_path)
            )

            # Transform contracts to adapter format (just decimals, not currency_id)
            contracts_for_adapter = {}
            for network, contracts in contracts_by_network.items():
                contracts_for_adapter[network] = {
                    addr: decimals for addr, (currency_id, decimals) in contracts.items()
                }

            # Initialize multi-chain adapter
            adapter = MultiChainAdapter(network_configs)

            # Fetch balances from all wallets
            all_balances = []

            for account_id, wallet_info in wallet_accounts.items():
                account_name = wallet_info["account_name"]
                addresses = wallet_info["addresses"]

                logger.info(f"Fetching from {account_name}...")

                try:
                    balances_by_network = adapter.fetch_wallet_balances(
                        wallet_addresses=addresses,
                        known_contracts=contracts_for_adapter,
                        native_decimals=native_decimals,
                    )

                    # Transform to database format
                    for network, balances in balances_by_network.items():
                        for balance in balances:
                            # Map contract address to currency_id
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
                                        "network": network,
                                        "currency_id": currency_id,
                                        "quantity": balance.balance,
                                    }
                                )
                            else:
                                logger.warning(
                                    f"  Skipping unknown contract: {balance.contract_address}"
                                )

                    logger.info(f"✓ {account_name}: Fetched balances from {len(addresses)} networks")

                except Exception as e:
                    logger.error(f"✗ {account_name}: Failed to fetch balances - {e}")
                    continue

            if not all_balances:
                logger.warning("No balances fetched from any wallet")
                sys.exit(0)

            logger.info(f"Total balances fetched: {len(all_balances)}")

            # NOTE: Zero-balance logic removed - use scripts/ingest_balances.py --sources all
            # to get complete snapshot with zero-balance tracking

            # Calculate values
            logger.info("Calculating USD and IDR values...")
            all_balances = calculate_values(all_balances, str(db_path))

            # Insert snapshot
            snapshot_time = datetime.now()
            logger.info(f"Creating snapshot at {snapshot_time.isoformat()}")
            inserted = insert_balances(all_balances, str(db_path), snapshot_time)

            # Summary
            logger.info("=" * 70)
            logger.info(f"✓ Successfully imported {inserted} on-chain balances")
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
