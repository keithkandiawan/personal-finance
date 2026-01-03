#!/usr/bin/env python3
"""
Bootstrap Currencies Script

Adds common cryptocurrencies and stablecoins to the database.
Run this once to initialize the currencies table with your holdings.

Usage:
    python scripts/bootstrap_currencies.py [database_path]
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def bootstrap_currencies(db_path: str):
    """Add currencies to database."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Get currency type IDs
    cursor.execute("SELECT id FROM currency_types WHERE name = 'crypto'")
    crypto_type_id = cursor.fetchone()[0]

    cursor.execute("SELECT id FROM currency_types WHERE name = 'stablecoin'")
    stablecoin_type_id = cursor.fetchone()[0]

    cursor.execute("SELECT id FROM currency_types WHERE name = 'fiat'")
    fiat_type_id = cursor.fetchone()[0]

    # Create 'stock' type if it doesn't exist
    cursor.execute("SELECT id FROM currency_types WHERE name = 'stock'")
    stock_row = cursor.fetchone()
    if stock_row:
        stock_type_id = stock_row[0]
    else:
        cursor.execute("INSERT INTO currency_types (name) VALUES ('stock')")
        stock_type_id = cursor.lastrowid
        print("✓ Created 'stock' currency type")

    # Create 'metal' type if it doesn't exist (for precious metals)
    cursor.execute("SELECT id FROM currency_types WHERE name = 'metal'")
    metal_row = cursor.fetchone()
    if metal_row:
        metal_type_id = metal_row[0]
    else:
        cursor.execute("INSERT INTO currency_types (name) VALUES ('metal')")
        metal_type_id = cursor.lastrowid
        print("✓ Created 'metal' currency type")

    # Define currencies to add
    # Format: (code, type_id)
    currencies = [
        # Fiat Currencies
        ("IDR", fiat_type_id),
        ("USD", fiat_type_id),
        ("SGD", fiat_type_id),
        # Major Stablecoins
        ("USDC", stablecoin_type_id),
        ("USDT", stablecoin_type_id),
        # Major Cryptocurrencies
        ("BTC", crypto_type_id),
        ("ETH", crypto_type_id),
        ("BNB", crypto_type_id),
        ("SOL", crypto_type_id),
        ("ADA", crypto_type_id),
        ("DOT", crypto_type_id),
        ("LINK", crypto_type_id),
        ("ATOM", crypto_type_id),
        ("NEAR", crypto_type_id),
        ("POL", crypto_type_id),
        ("ASTER", crypto_type_id),
        ("TON", crypto_type_id),
        ("TRX", crypto_type_id),
        # Exchange Tokens
        ("OKB", crypto_type_id),
        ("BGB", crypto_type_id),  # Bitget Token
        ("S", crypto_type_id),
        # Precious Metals & Metal-backed Tokens
        ("PAXG", metal_type_id),  # Paxos Gold (tokenized gold)
        ("XAUT", metal_type_id),  # Tether Gold (tokenized gold)
        ("GOLD", metal_type_id),  # Gold-backed token
        ("GLD", metal_type_id),   # SPDR Gold Shares ETF
        ("SLV", metal_type_id),   # iShares Silver Trust ETF
        # Stocks & ETFs
        ("DIS", stock_type_id),   # Disney
        ("SBUX", stock_type_id),  # Starbucks
        ("TLT", stock_type_id),   # iShares 20+ Year Treasury Bond ETF
    ]

    inserted = 0
    skipped = 0

    print("=" * 70)
    print("Currency Bootstrap")
    print("=" * 70)

    for code, type_id in currencies:
        try:
            # Check if currency already exists
            cursor.execute("SELECT id FROM currencies WHERE code = ?", (code,))
            if cursor.fetchone():
                print(f"⊘ {code:12} - Already exists, skipping")
                skipped += 1
                continue

            # Insert currency
            cursor.execute(
                """
                INSERT INTO currencies (code, type)
                VALUES (?, ?)
            """,
                (code, type_id),
            )

            print(f"✓ {code:12} - Added")
            inserted += 1

        except sqlite3.Error as e:
            print(f"✗ {code:12} - Error: {e}")

    conn.commit()
    conn.close()

    print("=" * 70)
    print(f"Summary: {inserted} added, {skipped} skipped")
    print("=" * 70)


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/portfolio.db"

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        print("Please create the database first using sql/schema.sql")
        sys.exit(1)

    bootstrap_currencies(db_path)
    print("\nNext steps:")
    print("1. Add TradingView symbol mappings for price tracking:")
    print("   python scripts/bootstrap_symbol_mappings.py")
    print("2. Fetch FX rates:")
    print("   python scripts/ingest_fx_rates.py")
    print("3. Try ingesting balances from exchanges:")
    print("   python scripts/ingest_balances.py --sources exchanges")


if __name__ == "__main__":
    main()
