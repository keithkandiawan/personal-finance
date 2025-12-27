"""
Personal Finance Tracker - Portfolio Management Package

This package provides tools for tracking and managing a personal investment portfolio
across multiple asset classes (crypto, stocks, ETFs, fiat) and data sources.
"""

__version__ = "0.1.0"

from .tradingview import (
    fetch_and_update_prices,
    check_stale_rates,
    get_tradingview_symbols,
)

from .exchanges import (
    create_exchange,
    BinanceAdapter,
    OKXAdapter,
    BitgetAdapter,
    Balance,
)

__all__ = [
    "fetch_and_update_prices",
    "check_stale_rates",
    "get_tradingview_symbols",
    "create_exchange",
    "BinanceAdapter",
    "OKXAdapter",
    "BitgetAdapter",
    "Balance",
]
