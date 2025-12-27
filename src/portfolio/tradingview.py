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


def get_tradingview_symbols(db_path: str) -> List[Tuple[int, str, str, bool]]:
    """
    Get all currencies that have TradingView symbol mappings and no parent currency.

    Currencies with parent_currency_id will inherit rates from their parent,
    so they don't need their own symbol mappings fetched.

    Args:
        db_path: Path to the SQLite database

    Returns:
        List of (currency_id, currency_code, tradingview_symbol, is_inverted) tuples
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("""
            SELECT
                c.id,
                c.code,
                sm.symbol,
                sm.is_inverted
            FROM currencies c
            INNER JOIN symbol_mappings sm ON c.id = sm.currency_id
            WHERE sm.source = 'tradingview'
              AND (c.parent_currency_id IS NULL OR c.parent_currency_id = c.id)
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
        rate: Exchange rate to USD (how many USD per 1 unit of currency)
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


def propagate_parent_rates(db_path: str) -> int:
    """
    Copy FX rates from parent currencies to child currencies.

    For currencies with parent_currency_id set (e.g., LDBNB → BNB),
    copies the parent's FX rate to the child.

    Args:
        db_path: Path to the SQLite database

    Returns:
        Number of child currencies updated
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Get all child currencies with their parent rates
        cursor = conn.execute("""
            SELECT
                child.id as child_id,
                child.code as child_code,
                parent.id as parent_id,
                parent.code as parent_code,
                fx.rate as parent_rate,
                fx.source as parent_source
            FROM currencies child
            INNER JOIN currencies parent ON child.parent_currency_id = parent.id
            INNER JOIN fx_rates fx ON parent.id = fx.currency_id
            WHERE child.parent_currency_id IS NOT NULL
              AND child.id != child.parent_currency_id
        """)

        children = cursor.fetchall()

        if not children:
            logger.info("No child currencies with parent rates found")
            return 0

        logger.info(f"Propagating rates to {len(children)} child currencies...")

        updated_count = 0
        for child in children:
            # Update child currency with parent's rate
            conn.execute("""
                INSERT INTO fx_rates (currency_id, rate, source, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(currency_id) DO UPDATE SET
                    rate = excluded.rate,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
            """, (child['child_id'], child['parent_rate'],
                  f"{child['parent_source']} (from {child['parent_code']})"))

            logger.info(f"  ✓ {child['child_code']} ← {child['parent_code']}: ${child['parent_rate']}")
            updated_count += 1

        conn.commit()
        return updated_count

    except sqlite3.Error as e:
        logger.error(f"Error propagating parent rates: {e}")
        return 0
    finally:
        conn.close()


def fetch_and_update_prices(db_path: str = 'portfolio.db') -> int:
    """
    Fetch prices from TradingView and update fx_rates table.
    Also propagates rates from parent currencies to child currencies.

    Args:
        db_path: Path to the SQLite database

    Returns:
        Number of successfully updated prices (including propagated child rates)
    """
    logger.info("Starting TradingView price fetch...")

    # Get all TradingView symbols (excludes child currencies with parents)
    symbols = get_tradingview_symbols(db_path)

    if not symbols:
        logger.warning("No TradingView symbol mappings found in database")
        return 0

    logger.info(f"Found {len(symbols)} parent currencies with TradingView mappings")

    # Fetch and update prices
    updated_count = 0
    failed_symbols = []

    for currency_id, currency_code, tv_symbol, is_inverted in symbols:
        logger.info(f"Processing {currency_code} ({tv_symbol})...")

        price = fetch_price_from_tradingview(tv_symbol)

        if price is not None:
            # Apply inversion if needed
            if is_inverted:
                rate = 1.0 / price if price != 0 else 0
                logger.info(f"Inverted {tv_symbol}: {price} → {rate:.8f}")
            else:
                rate = price

            if update_fx_rate(db_path, currency_id, rate):
                updated_count += 1
                logger.info(f"✓ Updated {currency_code}: ${rate}")
            else:
                failed_symbols.append((currency_code, "Database error"))
        else:
            failed_symbols.append((currency_code, "Fetch failed"))

    # Propagate parent rates to child currencies
    logger.info("=" * 60)
    child_count = propagate_parent_rates(db_path)
    total_updated = updated_count + child_count

    # Summary
    logger.info("=" * 60)
    logger.info(f"Price fetch complete: {updated_count}/{len(symbols)} parent currencies")
    logger.info(f"Child currencies updated: {child_count}")
    logger.info(f"Total updated: {total_updated}")

    if failed_symbols:
        logger.warning("Failed to update:")
        for symbol, reason in failed_symbols:
            logger.warning(f"  • {symbol}: {reason}")

    return total_updated


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
