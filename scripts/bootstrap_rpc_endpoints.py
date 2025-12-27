#!/usr/bin/env python3
"""
Bootstrap RPC Endpoints

Populates the networks table with RPC endpoint URLs from environment variables.
Run this after setting up RPC providers (Infura, Alchemy, etc.) in .env file.

Usage:
    python scripts/bootstrap_rpc_endpoints.py [database_path]

Required .env variables:
    ETHEREUM_RPC_URL - Ethereum mainnet RPC endpoint
    POLYGON_RPC_URL - Polygon RPC endpoint
    BSC_RPC_URL - BSC RPC endpoint
    ARBITRUM_RPC_URL - Arbitrum RPC endpoint
    OPTIMISM_RPC_URL - Optimism RPC endpoint
    BASE_RPC_URL - Base RPC endpoint
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment
load_dotenv()


def bootstrap_rpc_endpoints(db_path: str):
    """
    Populate RPC endpoints from environment variables into networks table.

    Args:
        db_path: Path to SQLite database
    """
    conn = sqlite3.connect(db_path)

    # Network to environment variable mapping
    rpc_config = {
        "ethereum": os.getenv("ETHEREUM_RPC_URL"),
        "polygon": os.getenv("POLYGON_RPC_URL"),
        "bsc": os.getenv("BSC_RPC_URL"),
        "arbitrum": os.getenv("ARBITRUM_RPC_URL"),
        "optimism": os.getenv("OPTIMISM_RPC_URL"),
        "base": os.getenv("BASE_RPC_URL"),
    }

    print("Updating RPC endpoints in networks table:")
    print("-" * 60)

    updated = 0
    for network_code, rpc_url in rpc_config.items():
        if rpc_url:
            conn.execute(
                "UPDATE networks SET rpc_endpoint = ? WHERE code = ?",
                (rpc_url, network_code),
            )
            if conn.total_changes > 0:
                updated += 1
                # Mask URL for security (show only first 30 chars)
                masked_url = rpc_url[:30] + "..." if len(rpc_url) > 30 else rpc_url
                print(f"✓ {network_code:12} - {masked_url}")
            else:
                print(f"⊘ {network_code:12} - Network not found in database")
        else:
            print(f"⊘ {network_code:12} - No RPC URL in .env")

    conn.commit()
    conn.close()

    print("-" * 60)
    print(f"Summary: {updated} networks configured")
    print()
    print("Next steps:")
    print("1. Add wallet addresses: python scripts/add_wallet_addresses.py")
    print("2. Discover tokens: python scripts/discover_tokens.py")
    print("3. Fetch balances: python scripts/ingest_onchain_balances.py")


def main():
    # Parse arguments
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/portfolio.db")

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Run: python scripts/init_db.py")
        sys.exit(1)

    bootstrap_rpc_endpoints(str(db_path))


if __name__ == "__main__":
    main()
