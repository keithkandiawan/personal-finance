#!/usr/bin/env python3
"""
Token Discovery Script

Scans EVM wallets for ERC-20 tokens and automatically populates the blockchain_contracts table.
Creates new currency entries for unknown tokens.

Usage:
    python scripts/discover_tokens.py [database_path]

Requirements:
    - RPC endpoints configured (run bootstrap_rpc_endpoints.py first)
    - Wallet addresses configured (run add_wallet_addresses.py first)
    - web3 library installed

This script:
1. Loads all active wallet addresses
2. Scans each wallet for ERC-20 tokens on each network
3. Fetches token metadata (symbol, name, decimals)
4. Creates currency entries for new tokens
5. Adds blockchain_contracts entries

Note: This only discovers tokens already in your wallet. To track additional tokens,
manually add them to blockchain_contracts or bootstrap_blockchain_mappings.py
"""

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from portfolio.blockchain import EVMAdapter

# Load environment
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_or_create_currency(conn: sqlite3.Connection, symbol: str, name: str = None) -> int:
    """
    Get currency_id by symbol, or create if doesn't exist.

    Args:
        conn: Database connection
        symbol: Currency symbol (e.g., "USDC")
        name: Optional currency name

    Returns:
        currency_id
    """
    cursor = conn.cursor()

    # Try to find existing currency (case-insensitive)
    cursor.execute("SELECT id FROM currencies WHERE LOWER(code) = LOWER(?)", (symbol,))
    result = cursor.fetchone()
    if result:
        logger.info(f"  Currency {symbol} already exists (id={result[0]})")
        return result[0]

    # Create new currency as crypto type
    cursor.execute("SELECT id FROM currency_types WHERE name = 'crypto'")
    crypto_type = cursor.fetchone()
    if not crypto_type:
        raise ValueError("Currency type 'crypto' not found in database")

    crypto_type_id = crypto_type[0]

    cursor.execute(
        "INSERT INTO currencies (code, type, name) VALUES (?, ?, ?)",
        (symbol.upper(), crypto_type_id, name),
    )
    currency_id = cursor.lastrowid
    logger.info(f"  Created new currency: {symbol.upper()} (id={currency_id})")

    return currency_id


def add_blockchain_contract(
    conn: sqlite3.Connection,
    currency_id: int,
    network: str,
    contract_address: str,
    decimals: int,
    name: str = None,
) -> bool:
    """
    Add contract mapping if doesn't exist.

    Args:
        conn: Database connection
        currency_id: Currency ID
        network: Network code (ethereum, polygon, etc.)
        contract_address: Token contract address
        decimals: Token decimals
        name: Optional token name for notes

    Returns:
        True if added, False if already exists
    """
    cursor = conn.cursor()

    # Check if contract already exists
    cursor.execute(
        """
        SELECT id FROM blockchain_contracts
        WHERE currency_id = ? AND network = ? AND LOWER(contract_address) = LOWER(?)
    """,
        (currency_id, network, contract_address),
    )

    if cursor.fetchone():
        logger.info(f"  Contract already exists for {network}")
        return False

    # Insert contract
    cursor.execute(
        """
        INSERT INTO blockchain_contracts (
            currency_id, network, contract_address, decimals,
            is_native, standard, notes
        ) VALUES (?, ?, ?, ?, 0, 'ERC-20', ?)
    """,
        (currency_id, network, contract_address.lower(), decimals, name),
    )

    logger.info(f"  Added contract for {network}: {contract_address[:10]}...")
    return True


def discover_wallet_tokens(db_path: str):
    """
    Discover tokens across all configured wallets.

    This scans each wallet address on each network and populates
    the blockchain_contracts table with discovered tokens.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get network configurations
    networks = {}
    for row in conn.execute(
        """
        SELECT code, chain_id, rpc_endpoint
        FROM networks
        WHERE is_active = 1 AND is_evm = 1 AND rpc_endpoint IS NOT NULL
    """
    ):
        networks[row["code"]] = {
            "chain_id": row["chain_id"],
            "rpc_endpoint": row["rpc_endpoint"],
        }

    if not networks:
        logger.error("No networks configured with RPC endpoints")
        logger.error("Run: python scripts/bootstrap_rpc_endpoints.py")
        sys.exit(1)

    logger.info(f"Configured networks: {', '.join(networks.keys())}")

    # Get wallet addresses
    wallet_addresses = {}
    for row in conn.execute(
        """
        SELECT account_name, network, address
        FROM active_wallet_addresses
        ORDER BY account_name, network
    """
    ):
        account = row["account_name"]
        if account not in wallet_addresses:
            wallet_addresses[account] = {}
        wallet_addresses[account][row["network"]] = row["address"]

    if not wallet_addresses:
        logger.error("No wallet addresses configured")
        logger.error("Run: python scripts/add_wallet_addresses.py")
        sys.exit(1)

    logger.info(f"Configured wallets: {', '.join(wallet_addresses.keys())}")

    # Get existing contracts to avoid re-scanning
    existing_contracts = set()
    for row in conn.execute(
        """
        SELECT network, LOWER(contract_address) as address
        FROM blockchain_contracts
        WHERE contract_address IS NOT NULL
    """
    ):
        existing_contracts.add((row["network"], row["address"]))

    logger.info(f"Existing contracts: {len(existing_contracts)}")

    # Discover tokens
    total_discovered = 0

    for account_name, addresses in wallet_addresses.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"Scanning: {account_name}")
        logger.info(f"{'='*60}")

        for network, address in addresses.items():
            if network not in networks:
                logger.warning(f"  {network}: No RPC endpoint, skipping")
                continue

            logger.info(f"\n{network} ({address[:10]}...):")

            try:
                # Initialize adapter for this network
                adapter = EVMAdapter(
                    rpc_url=networks[network]["rpc_endpoint"],
                    network=network,
                    chain_id=networks[network]["chain_id"],
                )

                # Get all known ERC-20 contracts for this network
                cursor = conn.execute(
                    """
                    SELECT contract_address
                    FROM blockchain_contracts
                    WHERE network = ? AND contract_address IS NOT NULL AND is_native = 0
                """,
                    (network,),
                )

                known_contracts = [row[0] for row in cursor.fetchall()]
                logger.info(f"  Checking {len(known_contracts)} known contracts...")

                # Scan for balances
                found = 0
                for contract_address in known_contracts:
                    try:
                        balance_raw = adapter.get_erc20_balance(contract_address, address)

                        if balance_raw > 0:
                            # Get metadata
                            metadata = adapter.get_token_metadata(contract_address)

                            if metadata:
                                # Check if this is a new discovery
                                if (network, contract_address.lower()) not in existing_contracts:
                                    logger.info(
                                        f"  ✓ Found NEW token: {metadata.symbol} (balance: {balance_raw / (10**metadata.decimals):.6f})"
                                    )

                                    # Create currency if needed
                                    currency_id = get_or_create_currency(
                                        conn, metadata.symbol, metadata.name
                                    )

                                    # Add contract
                                    added = add_blockchain_contract(
                                        conn,
                                        currency_id,
                                        network,
                                        contract_address,
                                        metadata.decimals,
                                        metadata.name,
                                    )

                                    if added:
                                        existing_contracts.add((network, contract_address.lower()))
                                        total_discovered += 1
                                        found += 1
                                else:
                                    logger.debug(
                                        f"  - {metadata.symbol} (already in database)"
                                    )

                    except Exception as e:
                        logger.debug(f"  Error checking {contract_address}: {e}")
                        continue

                if found > 0:
                    logger.info(f"  Discovered {found} new tokens on {network}")
                    conn.commit()
                else:
                    logger.info(f"  No new tokens discovered on {network}")

            except Exception as e:
                logger.error(f"  Error scanning {network}: {e}")
                continue

    logger.info(f"\n{'='*60}")
    logger.info(f"Total new tokens discovered: {total_discovered}")
    logger.info(f"{'='*60}")

    if total_discovered > 0:
        logger.info("\nNext steps:")
        logger.info("1. Add symbol mappings: python scripts/add_symbol_mappings.py")
        logger.info("2. Fetch FX rates: python scripts/ingest_fx_rates.py")
        logger.info("3. Ingest balances: python scripts/ingest_onchain_balances.py")
    else:
        logger.info("\nAll tokens already in database. You can now:")
        logger.info("1. Fetch balances: python scripts/ingest_onchain_balances.py")

    conn.close()


def main():
    # Parse arguments
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/portfolio.db")

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Run: python scripts/init_db.py")
        sys.exit(1)

    discover_wallet_tokens(str(db_path))


if __name__ == "__main__":
    main()
