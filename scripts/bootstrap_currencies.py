#!/usr/bin/env python3
"""
Bootstrap Currencies Script

Adds common cryptocurrencies and stablecoins to the database.
Run this once to initialize the currencies table with your holdings.

Usage:
    python scripts/bootstrap_currencies.py [database_path]
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime


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

    # Define currencies to add
    # Format: (code, type_id)
    currencies = [
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
        ("PAXG", crypto_type_id),

        # Exchange Tokens
        ("OKB", crypto_type_id),

        # Binance Liquid Staking Tokens
        ("LDBNB", crypto_type_id),
        ("LDBTC", crypto_type_id),
        ("LDETH", crypto_type_id),
        ("LDUSDT", crypto_type_id),
        ("LDUSDC", crypto_type_id),
        ("LDLINK", crypto_type_id),
        ("LDADA", crypto_type_id),
        ("LDATOM", crypto_type_id),
        ("LDDOT", crypto_type_id),
        ("LDPAXG", crypto_type_id),
        ("LDPOL", crypto_type_id),
        ("LDS", crypto_type_id),

        # Other Tokens (from your balances)
        ("SOLO", crypto_type_id),
        ("MORPHO", crypto_type_id),
        ("WAL", crypto_type_id),
        ("EUL", crypto_type_id),
        ("ENSO", crypto_type_id),
        ("YB", crypto_type_id),
        ("ZBT", crypto_type_id),
        ("TURTLE", crypto_type_id),
        ("S", crypto_type_id),
        ("2Z", crypto_type_id),
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
            cursor.execute("""
                INSERT INTO currencies (code, type)
                VALUES (?, ?)
            """, (code, type_id))

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
    print("   python scripts/add_symbol_mappings.py")
    print("2. Fetch FX rates:")
    print("   python scripts/ingest_fx_rates.py")
    print("3. Try crypto ingestion again:")
    print("   python scripts/ingest_crypto_balances.py")


if __name__ == "__main__":
    main()
