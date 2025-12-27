#!/usr/bin/env python3
"""
Add Wallet Addresses

Interactive script to add EVM wallet addresses to the wallet_addresses table.
Supports adding addresses for multiple networks per account.

Usage:
    python scripts/add_wallet_addresses.py [database_path]

Examples:
    # Add address for Cold Wallet Flex on Ethereum
    Account: Cold Wallet Flex
    Network: ethereum
    Address: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb3

    # Add same wallet on Polygon (same address, different network)
    Account: Cold Wallet Flex
    Network: polygon
    Address: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb3
"""

import sqlite3
import sys
from pathlib import Path

from web3 import Web3


def list_accounts(conn: sqlite3.Connection):
    """List all active wallet accounts."""
    print("\nActive wallet accounts:")
    print("-" * 60)
    cursor = conn.execute(
        """
        SELECT id, name, account_type, provider
        FROM asset_accounts
        WHERE account_type = 'wallet'
        ORDER BY id
    """
    )
    accounts = cursor.fetchall()

    if not accounts:
        print("No wallet accounts found.")
        print("Add accounts in scripts/bootstrap_accounts.py")
        return []

    for acc_id, name, provider, notes in accounts:
        print(f"[{acc_id}] {name:20} ({provider})")
        if notes:
            print(f"    {notes}")

    return accounts


def list_networks(conn: sqlite3.Connection):
    """List all active EVM networks."""
    print("\nAvailable EVM networks:")
    print("-" * 60)
    cursor = conn.execute(
        """
        SELECT code, name, chain_id
        FROM networks
        WHERE is_active = 1 AND is_evm = 1
        ORDER BY code
    """
    )
    networks = cursor.fetchall()

    for code, name, chain_id in networks:
        print(f"  {code:12} - {name:20} (Chain ID: {chain_id})")

    return [n[0] for n in networks]


def get_existing_addresses(conn: sqlite3.Connection, account_id: int):
    """Get existing addresses for an account."""
    cursor = conn.execute(
        """
        SELECT network, address, label
        FROM wallet_addresses
        WHERE account_id = ? AND is_active = 1
        ORDER BY network
    """,
        (account_id,),
    )
    addresses = cursor.fetchall()

    if addresses:
        print("\nExisting addresses for this account:")
        for network, address, label in addresses:
            label_str = f" ({label})" if label else ""
            print(f"  {network:12} - {address}{label_str}")


def validate_address(address: str) -> str:
    """Validate and checksum an Ethereum address."""
    if not address.startswith("0x"):
        raise ValueError("Address must start with 0x")

    if len(address) != 42:
        raise ValueError(f"Address must be 42 characters (got {len(address)})")

    # Convert to checksum address
    try:
        return Web3.to_checksum_address(address)
    except ValueError as e:
        raise ValueError(f"Invalid Ethereum address: {e}")


def add_address(
    conn: sqlite3.Connection,
    account_id: int,
    network: str,
    address: str,
    label: str = None,
):
    """Add a wallet address to the database."""
    try:
        # Validate and checksum
        checksum_address = validate_address(address)

        conn.execute(
            """
            INSERT INTO wallet_addresses (account_id, network, address, label)
            VALUES (?, ?, ?, ?)
        """,
            (account_id, network, checksum_address.lower(), label),
        )
        conn.commit()
        print(f"✓ Added {network} address: {checksum_address}")
        return True

    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            print(f"✗ Address already exists for this account/network combination")
        else:
            print(f"✗ Database error: {e}")
        return False

    except ValueError as e:
        print(f"✗ Validation error: {e}")
        return False

    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def interactive_add(db_path: str):
    """Interactive mode for adding wallet addresses."""
    conn = sqlite3.connect(db_path)

    try:
        while True:
            # List available accounts
            accounts = list_accounts(conn)
            if not accounts:
                break

            # List available networks
            network_codes = list_networks(conn)

            print("\n" + "=" * 60)
            print("Add Wallet Address")
            print("=" * 60)

            # Get account
            try:
                account_input = input("\nEnter account ID (or 'q' to quit): ").strip()
                if account_input.lower() == "q":
                    break

                account_id = int(account_input)

                # Verify account exists
                cursor = conn.execute(
                    "SELECT name FROM asset_accounts WHERE id = ? AND account_type = 'wallet'",
                    (account_id,),
                )
                account = cursor.fetchone()

                if not account:
                    print(f"✗ Account ID {account_id} not found or not a wallet account")
                    continue

                account_name = account[0]
                print(f"Selected: {account_name}")

                # Show existing addresses
                get_existing_addresses(conn, account_id)

            except ValueError:
                print("✗ Invalid account ID")
                continue

            # Get network
            network = (
                input(f"\nEnter network ({', '.join(network_codes[:3])}, ...): ").strip().lower()
            )
            if network not in network_codes:
                print(f"✗ Invalid network. Choose from: {', '.join(network_codes)}")
                continue

            # Get address
            address = input("\nEnter wallet address (0x...): ").strip()

            # Optional label
            label_input = input("Label (optional, press Enter to skip): ").strip()
            label = label_input if label_input else None

            # Add address
            success = add_address(conn, account_id, network, address, label)

            if success:
                # Ask if user wants to add another
                another = input("\nAdd another address? (y/n): ").strip().lower()
                if another != "y":
                    break
            else:
                retry = input("\nRetry? (y/n): ").strip().lower()
                if retry != "y":
                    break

    finally:
        conn.close()

    print("\n✓ Done!")
    print("\nNext steps:")
    print("1. Discover tokens: python scripts/discover_tokens.py")
    print("2. Fetch balances: python scripts/ingest_onchain_balances.py")


def main():
    # Parse arguments
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/portfolio.db")

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Run: python scripts/init_db.py")
        sys.exit(1)

    interactive_add(str(db_path))


if __name__ == "__main__":
    main()
