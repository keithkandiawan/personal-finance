#!/usr/bin/env python3
"""
Bootstrap Blockchain Mappings

Sets up:
1. Parent-child currency relationships (LD tokens → underlying assets)
2. Blockchain contract addresses for on-chain data fetching

Usage:
    python scripts/bootstrap_blockchain_mappings.py [database_path]
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def setup_blockchain_contracts(conn):
    """Add blockchain contract addresses for on-chain data fetching."""
    cursor = conn.cursor()

    # Format: (currency_code, network, contract_address, decimals, is_native, standard)
    # contract_address = None for native tokens
    contracts = [
        # Ethereum Mainnet
        ("ETH", "ethereum", None, 18, 1, "Native"),
        ("USDC", "ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6, 0, "ERC-20"),
        ("USDT", "ethereum", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6, 0, "ERC-20"),
        ("LINK", "ethereum", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18, 0, "ERC-20"),
        ("UNI", "ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18, 0, "ERC-20"),
        ("XAUT", "ethereum", "0x68749665FF8D2d112Fa859AA293F07A622782F38", 6, 0, "ERC-20"),
        # BNB Smart Chain (BSC)
        ("BNB", "bsc", None, 18, 1, "Native"),
        ("USDC", "bsc", "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18, 0, "BEP-20"),
        ("USDT", "bsc", "0x55d398326f99059fF775485246999027B3197955", 18, 0, "BEP-20"),
        ("ASTER", "bsc", "0x000Ae314E2A2172a039B26378814C252734f556A", 18, 0, "BEP-20"),
        # Polygon
        ("POL", "polygon", None, 18, 1, "Native"),  # MATIC → POL rebrand
        ("USDC", "polygon", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6, 0, "ERC-20"),
        ("USDT", "polygon", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6, 0, "ERC-20"),
        # Arbitrum
        ("ETH", "arbitrum", None, 18, 1, "Native"),
        ("USDC", "arbitrum", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6, 0, "ERC-20"),
        ("USDT", "arbitrum", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6, 0, "ERC-20"),
        # Optimism
        ("ETH", "optimism", None, 18, 1, "Native"),
        ("USDC", "optimism", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6, 0, "ERC-20"),
        # Base
        ("ETH", "base", None, 18, 1, "Native"),
        ("USDC", "base", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, 0, "ERC-20"),
        # Solana
        ("SOL", "solana", None, 9, 1, "Native"),
        ("USDC", "solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 6, 0, "SPL"),
        ("USDT", "solana", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", 6, 0, "SPL"),
    ]

    inserted = 0
    skipped = 0
    missing = 0

    print("\n" + "=" * 70)
    print("Setting up blockchain contract addresses")
    print("=" * 70)

    for currency_code, network, contract_address, decimals, is_native, standard in contracts:
        # Get currency ID
        cursor.execute("SELECT id FROM currencies WHERE code = ?", (currency_code,))
        result = cursor.fetchone()

        if not result:
            print(f"⊘ {currency_code:8} on {network:10} - Currency not found")
            missing += 1
            continue

        currency_id = result[0]

        # Check if mapping already exists
        cursor.execute(
            """
            SELECT id FROM blockchain_contracts
            WHERE currency_id = ? AND network = ?
        """,
            (currency_id, network),
        )

        if cursor.fetchone():
            print(f"⊘ {currency_code:8} on {network:10} - Already exists")
            skipped += 1
            continue

        # Insert contract
        cursor.execute(
            """
            INSERT INTO blockchain_contracts (
                currency_id, network, contract_address, decimals,
                is_native, standard, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                currency_id,
                network,
                contract_address,
                decimals,
                is_native,
                standard,
                datetime.now().isoformat(),
            ),
        )

        addr_display = contract_address[:10] + "..." if contract_address else "Native"
        print(f"✓ {currency_code:8} on {network:10} - {addr_display} ({standard})")
        inserted += 1

    conn.commit()
    print(f"Summary: {inserted} contracts added, {skipped} skipped, {missing} missing")
    return inserted


def setup_networks(conn):
    """Add network definitions."""
    cursor = conn.cursor()

    # Format: (code, name, chain_id, native_currency_code, explorer_url, is_evm)
    networks = [
        ("ethereum", "Ethereum Mainnet", 1, "ETH", "https://etherscan.io", 1),
        ("bsc", "BNB Smart Chain", 56, "BNB", "https://bscscan.com", 1),
        ("polygon", "Polygon", 137, "POL", "https://polygonscan.com", 1),
        ("arbitrum", "Arbitrum One", 42161, "ETH", "https://arbiscan.io", 1),
        ("optimism", "Optimism", 10, "ETH", "https://optimistic.etherscan.io", 1),
        ("base", "Base", 8453, "ETH", "https://basescan.org", 1),
        ("solana", "Solana", None, "SOL", "https://solscan.io", 0),
    ]

    inserted = 0
    skipped = 0

    print("\n" + "=" * 70)
    print("Setting up blockchain networks")
    print("=" * 70)

    for code, name, chain_id, native_currency_code, explorer_url, is_evm in networks:
        # Get native currency ID
        cursor.execute("SELECT id FROM currencies WHERE code = ?", (native_currency_code,))
        result = cursor.fetchone()
        native_currency_id = result[0] if result else None

        # Check if network already exists
        cursor.execute("SELECT id FROM networks WHERE code = ?", (code,))
        if cursor.fetchone():
            print(f"⊘ {code:12} - Already exists")
            skipped += 1
            continue

        # Insert network
        chain_id_str = f"Chain ID: {chain_id}" if chain_id else "Non-EVM"
        cursor.execute(
            """
            INSERT INTO networks (
                code, name, chain_id, native_currency_id,
                explorer_url, is_evm, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                code,
                name,
                chain_id,
                native_currency_id,
                explorer_url,
                is_evm,
                datetime.now().isoformat(),
            ),
        )

        print(f"✓ {code:12} - {name:20} ({chain_id_str})")
        inserted += 1

    conn.commit()
    print(f"Summary: {inserted} networks added, {skipped} skipped")
    return inserted


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/portfolio.db"

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    # Check if migration has been run
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(currencies)")
    columns = [col[1] for col in cursor.fetchall()]

    if "parent_currency_id" not in columns:
        print("Error: Migration 001_add_blockchain_support.sql has not been run")
        print("\nRun this first:")
        print("  sqlite3 data/portfolio.db < sql/migrations/001_add_blockchain_support.sql")
        conn.close()
        sys.exit(1)

    print("=" * 70)
    print("Blockchain Mappings Bootstrap")
    print("=" * 70)

    # Run all setups
    setup_networks(conn)
    setup_blockchain_contracts(conn)

    conn.close()

    print("\n" + "=" * 70)
    print("Bootstrap complete!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Update FX rates to use parent currency prices:")
    print("   python scripts/ingest_fx_rates.py")
    print("2. Test crypto ingestion:")
    print("   python scripts/ingest_crypto_balances.py")
    print("3. Later: Build blockchain ingestion script using contract addresses")


if __name__ == "__main__":
    main()
