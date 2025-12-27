#!/usr/bin/env python3
"""
TradingView Price Fetcher - Helper Module

Fetches current prices from TradingView for all currencies with TradingView symbol mappings.
Updates the fx_rates table with the latest prices.

Requirements:
    pip install --upgrade --no-cache tradingview-scraper

Usage:
    from portfolio.tradingview import fetch_and_update_prices

    updated_count = fetch_and_update_prices('portfolio.db')
    print(f"Updated {updated_count} prices")
"""

import sqlite3
from datetime import datetime
from typing import Optional, Dict, List, Tuple
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_tradingview_symbols(db_path: str) -> List[Tuple[int, str, str]]:
    """
    Get all currencies that have TradingView symbol mappings.

    Args:
        db_path: Path to the SQLite database

    Returns:
        List of (currency_id, currency_code, tradingview_symbol) tuples
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("""
            SELECT
                c.id,
                c.code,
                sm.symbol
            FROM currencies c
            INNER JOIN symbol_mappings sm ON c.id = sm.currency_id
            WHERE sm.source = 'tradingview'
            ORDER BY c.code
        """)
        return cursor.fetchall()
    finally:
        conn.close()


def fetch_price_from_tradingview(symbol: str) -> Optional[float]:
    """
    Fetch current price from TradingView for a given symbol.

    Args:
        symbol: TradingView symbol in format 'VENUE:TICKER' (e.g., 'NASDAQ:AAPL')

    Returns:
        Current price as float, or None if fetch fails
    """
    try:
        from tradingview_scraper.symbols.overview import Overview

        ov = Overview()
        data = ov.get_symbol_overview(symbol)

        if data and 'data' in data and 'close' in data['data']:
            price = data['data']['close']
            logger.info(f"Fetched {symbol}: {price}")
            return float(price)
        else:
            logger.warning(f"No price data for {symbol}")
            return None

    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None


def update_fx_rate(
    db_path: str,
    currency_id: int,
    rate: float,
    source: str = 'tradingview'
) -> bool:
    """
    Update or insert FX rate for a currency.

    Args:
        db_path: Path to the SQLite database
        currency_id: ID of the currency
        rate: Exchange rate to USD
        source: Data source name

    Returns:
        True if successful, False otherwise
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        # Use INSERT OR REPLACE to handle both new and existing rates
        conn.execute("""
            INSERT INTO fx_rates (currency_id, rate, source, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(currency_id) DO UPDATE SET
                rate = excluded.rate,
                source = excluded.source,
                updated_at = CURRENT_TIMESTAMP
        """, (currency_id, rate, source))

        conn.commit()
        return True

    except sqlite3.Error as e:
        logger.error(f"Database error updating currency_id {currency_id}: {e}")
        return False
    finally:
        conn.close()


def fetch_and_update_prices(db_path: str = 'portfolio.db') -> int:
    """
    Fetch prices from TradingView and update fx_rates table.

    Args:
        db_path: Path to the SQLite database

    Returns:
        Number of successfully updated prices
    """
    logger.info("Starting TradingView price fetch...")

    # Get all TradingView symbols
    symbols = get_tradingview_symbols(db_path)

    if not symbols:
        logger.warning("No TradingView symbol mappings found in database")
        return 0

    logger.info(f"Found {len(symbols)} currencies with TradingView mappings")

    # Fetch and update prices
    updated_count = 0
    failed_symbols = []

    for currency_id, currency_code, tv_symbol in symbols:
        logger.info(f"Processing {currency_code} ({tv_symbol})...")

        price = fetch_price_from_tradingview(tv_symbol)

        if price is not None:
            if update_fx_rate(db_path, currency_id, price):
                updated_count += 1
                logger.info(f"✓ Updated {currency_code}: ${price}")
            else:
                failed_symbols.append((currency_code, "Database error"))
        else:
            failed_symbols.append((currency_code, "Fetch failed"))

    # Summary
    logger.info("=" * 60)
    logger.info(f"Price fetch complete: {updated_count}/{len(symbols)} successful")

    if failed_symbols:
        logger.warning("Failed to update:")
        for symbol, reason in failed_symbols:
            logger.warning(f"  • {symbol}: {reason}")

    return updated_count


def check_stale_rates(db_path: str = 'portfolio.db', hours: int = 24) -> List[Dict]:
    """
    Check for stale FX rates (older than specified hours).

    Args:
        db_path: Path to the SQLite database
        hours: Number of hours to consider stale (default: 24)

    Returns:
        List of stale rate dictionaries
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute("""
            SELECT
                c.code as currency_code,
                fx.rate,
                fx.source,
                fx.updated_at,
                ROUND((julianday('now') - julianday(fx.updated_at)) * 24, 1) as hours_old
            FROM fx_rates fx
            INNER JOIN currencies c ON fx.currency_id = c.id
            WHERE (julianday('now') - julianday(fx.updated_at)) * 24 > ?
            ORDER BY fx.updated_at ASC
        """, (hours,))

        return [dict(row) for row in cursor.fetchall()]

    finally:
        conn.close()


def main():
    """Main entry point for command-line usage."""
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else 'portfolio.db'

    # Fetch and update prices
    updated_count = fetch_and_update_prices(db_path)

    # Check for stale rates
    stale = check_stale_rates(db_path)

    if stale:
        logger.warning(f"\n⚠️  Found {len(stale)} stale rates (>24h old):")
        for rate in stale:
            logger.warning(
                f"  • {rate['currency_code']}: "
                f"{rate['hours_old']:.1f}h old (last: {rate['updated_at']})"
            )

    sys.exit(0 if updated_count > 0 else 1)


if __name__ == "__main__":
    main()
