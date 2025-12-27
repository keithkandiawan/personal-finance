#!/usr/bin/env python3
"""
Example: Setting up currencies and TradingView symbol mappings

This script demonstrates how to:
1. Add currencies to the database
2. Map them to TradingView symbols
3. Fetch prices using the TradingView helper

Usage:
    python example_setup.py
"""

import sqlite3
import sys
from pathlib import Path

# Add src directory to path to import portfolio package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from portfolio.tradingview import fetch_and_update_prices


def add_currency(conn, code: str, currency_type: str) -> int:
    """
    Add a currency to the database.

    Args:
        conn: SQLite connection
        code: Currency code (e.g., 'AAPL', 'BTC', 'USD')
        currency_type: Type of currency ('fiat', 'crypto', 'stablecoin', 'stock', 'etf')

    Returns:
        Currency ID
    """
    # Get currency_type_id
    cursor = conn.execute(
        "SELECT id FROM currency_types WHERE name = ?",
        (currency_type,)
    )
    type_id = cursor.fetchone()[0]

    # Insert or get existing currency
    cursor = conn.execute(
        "INSERT OR IGNORE INTO currencies (code, type) VALUES (?, ?)",
        (code, type_id)
    )
    conn.commit()

    # Get currency ID
    cursor = conn.execute("SELECT id FROM currencies WHERE code = ?", (code,))
    return cursor.fetchone()[0]


def add_symbol_mapping(
    conn,
    currency_id: int,
    source: str,
    symbol: str,
    is_primary: bool = True
):
    """
    Add a symbol mapping for a currency.

    Args:
        conn: SQLite connection
        currency_id: ID of the currency
        source: Data source ('tradingview', 'binance', etc.)
        symbol: Symbol at that source ('NASDAQ:AAPL', 'BTCUSDT', etc.)
        is_primary: Whether this is the primary source for this currency
    """
    conn.execute("""
        INSERT OR REPLACE INTO symbol_mappings (currency_id, source, symbol, is_primary)
        VALUES (?, ?, ?, ?)
    """, (currency_id, source, symbol, 1 if is_primary else 0))
    conn.commit()


def setup_example_currencies(db_path: str = 'portfolio.db'):
    """
    Setup example currencies with TradingView mappings.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        print("Setting up example currencies...\n")

        # Example 1: Stocks
        print("Adding stocks...")
        aapl_id = add_currency(conn, 'AAPL', 'stock')
        add_symbol_mapping(conn, aapl_id, 'tradingview', 'NASDAQ:AAPL')
        print(f"  ✓ AAPL (Apple Inc.) -> NASDAQ:AAPL")

        msft_id = add_currency(conn, 'MSFT', 'stock')
        add_symbol_mapping(conn, msft_id, 'tradingview', 'NASDAQ:MSFT')
        print(f"  ✓ MSFT (Microsoft) -> NASDAQ:MSFT")

        # Example 2: Crypto
        print("\nAdding cryptocurrencies...")
        btc_id = add_currency(conn, 'BTC', 'crypto')
        add_symbol_mapping(conn, btc_id, 'tradingview', 'BINANCE:BTCUSDT')
        print(f"  ✓ BTC (Bitcoin) -> BINANCE:BTCUSDT")

        eth_id = add_currency(conn, 'ETH', 'crypto')
        add_symbol_mapping(conn, eth_id, 'tradingview', 'BINANCE:ETHUSDT')
        print(f"  ✓ ETH (Ethereum) -> BINANCE:ETHUSDT")

        # Example 3: Stablecoins
        print("\nAdding stablecoins...")
        usdt_id = add_currency(conn, 'USDT', 'stablecoin')
        add_symbol_mapping(conn, usdt_id, 'tradingview', 'BINANCE:USDTUSD')
        print(f"  ✓ USDT (Tether) -> BINANCE:USDTUSD")

        # Example 4: ETFs
        print("\nAdding ETFs...")
        spy_id = add_currency(conn, 'SPY', 'etf')
        add_symbol_mapping(conn, spy_id, 'tradingview', 'AMEX:SPY')
        print(f"  ✓ SPY (S&P 500 ETF) -> AMEX:SPY")

        # Example 5: Fiat (if needed for FX rates)
        print("\nAdding fiat currencies...")
        idr_id = add_currency(conn, 'IDR', 'fiat')
        add_symbol_mapping(conn, idr_id, 'tradingview', 'FX:USDIDR')
        print(f"  ✓ IDR (Indonesian Rupiah) -> FX:USDIDR")

        usd_id = add_currency(conn, 'USD', 'fiat')
        # USD doesn't need a mapping since all rates are to USD
        print(f"  ✓ USD (US Dollar) - base currency")

        print("\n✓ Setup complete!")

    finally:
        conn.close()


def main():
    """Main entry point."""
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else 'portfolio.db'

    # Setup currencies and mappings
    setup_example_currencies(db_path)

    # Fetch prices from TradingView
    print("\n" + "=" * 60)
    print("Fetching prices from TradingView...")
    print("=" * 60 + "\n")

    updated_count = fetch_and_update_prices(db_path)

    if updated_count > 0:
        print(f"\n✓ Successfully updated {updated_count} prices!")

        # Display the rates
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("""
            SELECT
                c.code,
                fx.rate,
                fx.updated_at
            FROM fx_rates fx
            INNER JOIN currencies c ON fx.currency_id = c.id
            ORDER BY c.code
        """)

        print("\nCurrent FX Rates (to USD):")
        print("-" * 60)
        for code, rate, updated_at in cursor.fetchall():
            print(f"  {code:6s} = ${rate:>12,.2f}  (updated: {updated_at})")

        conn.close()
    else:
        print("\n✗ No prices were updated. Check the logs for errors.")


if __name__ == "__main__":
    main()
