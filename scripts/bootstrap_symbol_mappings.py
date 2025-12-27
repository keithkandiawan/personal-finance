#!/usr/bin/env python3
"""
Add TradingView Symbol Mappings

Maps currencies to TradingView symbols for price fetching.
Run this after bootstrapping currencies.

Usage:
    python scripts/add_symbol_mappings.py [database_path]
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def add_symbol_mappings(db_path: str):
    """Add TradingView symbol mappings for currencies."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Symbol mappings: (currency_code, tradingview_symbol, is_inverted, is_primary)
    # is_inverted=1 means the symbol shows XXX/USD, need to invert (1/rate)
    # is_primary=1 means this is the preferred symbol for this currency
    mappings = [
        # Major Stablecoins (pegged to USD)
        ("USDC", "BINANCE:USDCUSDT", 0, 1),  # ~1.00 USD
        ("USDT", "BINANCE:USDTUSD", 0, 1),  # ~1.00 USD
        # Major Cryptocurrencies
        ("BTC", "BINANCE:BTCUSDT", 0, 1),
        ("ETH", "BINANCE:ETHUSDT", 0, 1),
        ("BNB", "BINANCE:BNBUSDT", 0, 1),
        ("SOL", "BINANCE:SOLUSDT", 0, 1),
        ("ADA", "BINANCE:ADAUSDT", 0, 1),
        ("DOT", "BINANCE:DOTUSDT", 0, 1),
        ("LINK", "BINANCE:LINKUSDT", 0, 1),
        ("ATOM", "BINANCE:ATOMUSDT", 0, 1),
        ("NEAR", "BINANCE:NEARUSDT", 0, 1),
        ("POL", "BINANCE:POLUSDT", 0, 1),
        ("PAXG", "BINANCE:PAXGUSDT", 0, 1),
        # Exchange Tokens
        ("OKB", "OKX:OKBUSDT", 0, 1),
        ("IDR", "FX_IDC:USDIDR", 1, 1),
    ]

    inserted = 0
    skipped = 0
    missing = 0

    print("=" * 70)
    print("TradingView Symbol Mappings")
    print("=" * 70)

    for currency_code, tv_symbol, is_inverted, is_primary in mappings:
        try:
            # Get currency ID
            cursor.execute("SELECT id FROM currencies WHERE code = ?", (currency_code,))
            result = cursor.fetchone()

            if not result:
                print(f"⊘ {currency_code:12} - Currency not in database, add it first")
                missing += 1
                continue

            currency_id = result[0]

            # Check if mapping already exists
            cursor.execute(
                """
                SELECT id FROM symbol_mappings
                WHERE currency_id = ? AND source = 'tradingview'
            """,
                (currency_id,),
            )

            if cursor.fetchone():
                print(f"⊘ {currency_code:12} - Mapping already exists")
                skipped += 1
                continue

            # Insert mapping
            cursor.execute(
                """
                INSERT INTO symbol_mappings (
                    currency_id, source, symbol, is_inverted, is_primary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    currency_id,
                    "tradingview",
                    tv_symbol,
                    is_inverted,
                    is_primary,
                    datetime.now().isoformat(),
                ),
            )

            invert_note = " (inverted)" if is_inverted else ""
            print(f"✓ {currency_code:12} → {tv_symbol}{invert_note}")
            inserted += 1

        except sqlite3.Error as e:
            print(f"✗ {currency_code:12} - Error: {e}")

    conn.commit()
    conn.close()

    print("=" * 70)
    print(f"Summary: {inserted} added, {skipped} skipped, {missing} missing")
    print("=" * 70)

    if missing > 0:
        print("\nNote: Some currencies don't have mappings yet.")
        print("For tokens without TradingView symbols (WAL, ENSO, YB, ZBT, TURTLE, S, 2Z, LDS):")
        print("- Their balances will still be tracked (in quantity)")
        print("- USD/IDR values will be NULL until you add custom symbol mappings")
        print("- You can manually add mappings later if you find their symbols")


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/portfolio.db"

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    add_symbol_mappings(db_path)
    print("\nNext steps:")
    print("1. Fetch FX rates: python scripts/ingest_fx_rates.py")
    print("2. Test crypto ingestion: python scripts/ingest_crypto_balances.py")


if __name__ == "__main__":
    main()
