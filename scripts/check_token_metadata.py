#!/usr/bin/env python3
"""
Quick script to check token metadata for an unknown contract address.
Usage: python scripts/check_token_metadata.py <network> <contract_address>
"""

import sys
from pathlib import Path
import sqlite3
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from portfolio.blockchain import EVMAdapter

load_dotenv()

def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/check_token_metadata.py <network> <contract_address>")
        print("Example: python scripts/check_token_metadata.py bsc 0x000ae314e2a2172a039b26378814c252734f556a")
        sys.exit(1)

    network = sys.argv[1]
    contract_address = sys.argv[2]

    # Get network config from database
    db_path = Path("data/portfolio.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    network_info = conn.execute(
        "SELECT code, chain_id, rpc_endpoint FROM networks WHERE code = ? AND is_active = 1",
        (network,)
    ).fetchone()

    if not network_info:
        print(f"Error: Network '{network}' not found in database")
        sys.exit(1)

    if not network_info['rpc_endpoint']:
        print(f"Error: No RPC endpoint configured for {network}")
        print("Run: python scripts/bootstrap_rpc_endpoints.py")
        sys.exit(1)

    conn.close()

    # Query token metadata
    print(f"\nQuerying {network} for {contract_address}...")
    print("-" * 60)

    try:
        adapter = EVMAdapter(
            rpc_url=network_info['rpc_endpoint'],
            network=network,
            chain_id=network_info['chain_id']
        )

        metadata = adapter.get_token_metadata(contract_address)

        if metadata:
            print(f"Symbol:   {metadata.symbol}")
            print(f"Name:     {metadata.name}")
            print(f"Decimals: {metadata.decimals}")
            print(f"Contract: {metadata.contract_address}")
            print("\nTo add this token to your database:")
            print(f"1. Use discover_tokens.py to add it automatically")
            print(f"2. Or manually add to currencies + blockchain_contracts tables")
        else:
            print("Error: Could not fetch token metadata")
            print("This might not be a valid ERC-20 contract")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
