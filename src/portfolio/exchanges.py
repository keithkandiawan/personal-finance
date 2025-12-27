"""
Crypto Exchange Integration

Provides adapters for fetching balances from various crypto exchanges.
Uses CCXT library for unified exchange API access.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import ccxt

logger = logging.getLogger(__name__)


@dataclass
class Balance:
    """Represents a currency balance on an exchange."""

    currency: str  # Currency code (BTC, ETH, USDT, etc.)
    total: float  # Total balance (available + locked)
    free: float  # Available balance
    used: float  # Locked balance (in orders)


class ExchangeAdapter:
    """Base class for exchange adapters."""

    def __init__(self, api_key: str, api_secret: str, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = None

    def fetch_balances(self) -> List[Balance]:
        """
        Fetch all non-zero balances from the exchange.

        Returns:
            List of Balance objects
        """
        raise NotImplementedError

    def test_connection(self) -> bool:
        """Test if API credentials are valid."""
        try:
            self.exchange.fetch_balance()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False


class BinanceAdapter(ExchangeAdapter):
    """Binance exchange adapter."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        super().__init__(api_key, api_secret)

        self.exchange = ccxt.binance(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",  # spot, margin, future
                },
            }
        )

        if testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch_balances(self) -> List[Balance]:
        """Fetch Binance balances from all account types (spot, margin, future, funding, earn)."""
        aggregated = {}  # {currency: {'total': x, 'free': y, 'used': z}}

        # Fetch from standard account types
        account_types = ["spot", "margin", "future", "funding"]
        for account_type in account_types:
            try:
                self.exchange.options["defaultType"] = account_type
                balance_data = self.exchange.fetch_balance()

                fetched_count = 0
                for currency, amounts in balance_data.get("total", {}).items():
                    if amounts and amounts > 0:
                        if currency not in aggregated:
                            aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                        aggregated[currency]["total"] += amounts
                        aggregated[currency]["free"] += balance_data["free"].get(currency, 0)
                        aggregated[currency]["used"] += balance_data["used"].get(currency, 0)
                        fetched_count += 1

                if fetched_count > 0:
                    logger.info(f"  Binance {account_type}: {fetched_count} currencies")

            except Exception as e:
                logger.debug(f"  Binance {account_type}: Not accessible or empty ({e})")
                continue

        # Fetch from Simple Earn (Flexible Savings)
        try:
            earn_positions = self.exchange.sapi_get_simple_earn_flexible_position()
            earn_count = 0
            if "rows" in earn_positions:
                for position in earn_positions["rows"]:
                    currency = position.get("asset")
                    # totalAmount includes both free and locked
                    amount = float(position.get("totalAmount", 0))

                    if amount > 0:
                        if currency not in aggregated:
                            aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                        aggregated[currency]["total"] += amount
                        aggregated[currency]["free"] += amount  # Flexible is available
                        earn_count += 1

            if earn_count > 0:
                logger.info(f"  Binance earn (flexible): {earn_count} currencies")

        except Exception as e:
            logger.debug(f"  Binance earn (flexible): Not accessible ({e})")

        # Fetch from Simple Earn (Locked Savings)
        try:
            locked_positions = self.exchange.sapi_get_simple_earn_locked_position()
            locked_count = 0
            if "rows" in locked_positions:
                for position in locked_positions["rows"]:
                    currency = position.get("asset")
                    amount = float(position.get("amount", 0))

                    if amount > 0:
                        if currency not in aggregated:
                            aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                        aggregated[currency]["total"] += amount
                        aggregated[currency]["used"] += amount  # Locked is not available
                        locked_count += 1

            if locked_count > 0:
                logger.info(f"  Binance earn (locked): {locked_count} currencies")

        except Exception as e:
            logger.debug(f"  Binance earn (locked): Not accessible ({e})")

        # Convert aggregated dict to Balance objects
        balances = [
            Balance(
                currency=currency,
                total=amounts["total"],
                free=amounts["free"],
                used=amounts["used"],
            )
            for currency, amounts in aggregated.items()
        ]

        logger.info(f"Binance total: {len(balances)} currencies across all accounts")
        return balances


class OKXAdapter(ExchangeAdapter):
    """OKX exchange adapter."""

    def __init__(self, api_key: str, api_secret: str, password: str, testnet: bool = False):
        super().__init__(api_key, api_secret)
        self.password = password

        self.exchange = ccxt.okx(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "password": password,
                "enableRateLimit": True,
            }
        )

        if testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch_balances(self) -> List[Balance]:
        """Fetch OKX balances from all account types (trading, funding, earn)."""
        aggregated = {}  # {currency: {'total': x, 'free': y, 'used': z}}

        # Try unified balance first (returns all accounts)
        try:
            balance_data = self.exchange.fetch_balance()

            fetched_count = 0
            for currency, amounts in balance_data.get("total", {}).items():
                if amounts and amounts > 0:
                    if currency not in aggregated:
                        aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                    aggregated[currency]["total"] += amounts
                    aggregated[currency]["free"] += balance_data["free"].get(currency, 0)
                    aggregated[currency]["used"] += balance_data["used"].get(currency, 0)
                    fetched_count += 1

            if fetched_count > 0:
                logger.info(f"  OKX unified: {fetched_count} currencies")

        except Exception as e:
            logger.debug(f"  OKX unified balance failed, trying individual accounts: {e}")

            # Fallback: Try individual account types
            account_types = ["trading", "funding"]
            for account_type in account_types:
                try:
                    balance_data = self.exchange.fetch_balance({"type": account_type})

                    fetched_count = 0
                    for currency, amounts in balance_data.get("total", {}).items():
                        if amounts and amounts > 0:
                            if currency not in aggregated:
                                aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                            aggregated[currency]["total"] += amounts
                            aggregated[currency]["free"] += balance_data["free"].get(currency, 0)
                            aggregated[currency]["used"] += balance_data["used"].get(currency, 0)
                            fetched_count += 1

                    if fetched_count > 0:
                        logger.info(f"  OKX {account_type}: {fetched_count} currencies")

                except Exception as e:
                    logger.debug(f"  OKX {account_type}: Not accessible or empty ({e})")
                    continue

        # Fetch from Earn (savings products)
        try:
            # OKX savings are typically shown in the funding account
            # But we can also try the private API for earn products
            earn_data = self.exchange.private_get_finance_savings_balance()
            earn_count = 0

            if "data" in earn_data:
                for position in earn_data["data"]:
                    currency = position.get("ccy")
                    amount = float(position.get("amt", 0))

                    if amount > 0:
                        if currency not in aggregated:
                            aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                        aggregated[currency]["total"] += amount
                        aggregated[currency]["used"] += amount  # Earn products are locked
                        earn_count += 1

            if earn_count > 0:
                logger.info(f"  OKX earn: {earn_count} currencies")

        except Exception as e:
            logger.debug(f"  OKX earn: Not accessible ({e})")

        # Fetch from Staking - get ACTIVE positions (not offers)
        staking_count = 0

        try:
            # Get active staking positions
            if hasattr(self.exchange, "privateGetFinanceStakingDefiOrdersActive"):
                staking_data = self.exchange.privateGetFinanceStakingDefiOrdersActive()

                if "data" in staking_data and staking_data["data"]:
                    for order in staking_data["data"]:
                        currency = order.get("ccy")

                        # Get staked amount from investData
                        if "investData" in order:
                            for invest in order.get("investData", []):
                                amount = float(invest.get("amt", 0))

                                if amount > 0 and currency:
                                    if currency not in aggregated:
                                        aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                                    aggregated[currency]["total"] += amount
                                    aggregated[currency]["used"] += amount  # Staked funds are locked
                                    staking_count += 1
        except Exception as e:
            logger.debug(f"  OKX staking: {e}")

        # Try ETH 2.0 staking
        try:
            if hasattr(self.exchange, "privateGetFinanceStakingDefiEthBalance"):
                eth_staking = self.exchange.privateGetFinanceStakingDefiEthBalance()

                if "data" in eth_staking:
                    for position in eth_staking["data"]:
                        currency = position.get("ccy", "BETH")
                        amount = float(position.get("amt", 0))

                        if amount > 0:
                            if currency not in aggregated:
                                aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                            aggregated[currency]["total"] += amount
                            aggregated[currency]["used"] += amount
                            staking_count += 1
        except Exception as e:
            logger.debug(f"  OKX ETH staking: {e}")

        if staking_count > 0:
            logger.info(f"  OKX staking: {staking_count} positions")

        # Convert aggregated dict to Balance objects
        balances = [
            Balance(
                currency=currency,
                total=amounts["total"],
                free=amounts["free"],
                used=amounts["used"],
            )
            for currency, amounts in aggregated.items()
        ]

        logger.info(f"OKX total: {len(balances)} currencies across all accounts")
        return balances


class BitgetAdapter(ExchangeAdapter):
    """Bitget exchange adapter."""

    def __init__(self, api_key: str, api_secret: str, password: str, testnet: bool = False):
        super().__init__(api_key, api_secret)
        self.password = password

        self.exchange = ccxt.bitget(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "password": password,
                "enableRateLimit": True,
            }
        )

        if testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch_balances(self) -> List[Balance]:
        """Fetch Bitget balances from all account types (spot, margin, swap, earn)."""
        aggregated = {}  # {currency: {'total': x, 'free': y, 'used': z}}

        # Fetch from different account types
        account_types = ["spot", "margin", "swap"]
        for account_type in account_types:
            try:
                balance_data = self.exchange.fetch_balance({"type": account_type})

                fetched_count = 0
                for currency, amounts in balance_data.get("total", {}).items():
                    if amounts and amounts > 0:
                        if currency not in aggregated:
                            aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                        aggregated[currency]["total"] += amounts
                        aggregated[currency]["free"] += balance_data["free"].get(currency, 0)
                        aggregated[currency]["used"] += balance_data["used"].get(currency, 0)
                        fetched_count += 1

                if fetched_count > 0:
                    logger.info(f"  Bitget {account_type}: {fetched_count} currencies")

            except Exception as e:
                logger.debug(f"  Bitget {account_type}: Not accessible or empty ({e})")
                continue

        # Try to fetch from Earn products
        try:
            # Bitget earn products - try private API
            earn_data = self.exchange.private_get_v2_earn_savings_account()
            earn_count = 0

            if "data" in earn_data and "productList" in earn_data["data"]:
                for product in earn_data["data"]["productList"]:
                    currency = product.get("coin")
                    amount = float(product.get("amount", 0))

                    if amount > 0:
                        if currency not in aggregated:
                            aggregated[currency] = {"total": 0, "free": 0, "used": 0}

                        aggregated[currency]["total"] += amount
                        # Check if it's flexible or locked
                        product_type = product.get("productType", "")
                        if "flexible" in product_type.lower():
                            aggregated[currency]["free"] += amount
                        else:
                            aggregated[currency]["used"] += amount
                        earn_count += 1

            if earn_count > 0:
                logger.info(f"  Bitget earn: {earn_count} currencies")

        except Exception as e:
            logger.debug(f"  Bitget earn: Not accessible ({e})")

        # Convert aggregated dict to Balance objects
        balances = [
            Balance(
                currency=currency,
                total=amounts["total"],
                free=amounts["free"],
                used=amounts["used"],
            )
            for currency, amounts in aggregated.items()
        ]

        logger.info(f"Bitget total: {len(balances)} currencies across all accounts")
        return balances


def create_exchange(
    exchange_name: str,
    api_key: str,
    api_secret: str,
    password: Optional[str] = None,
    testnet: bool = False,
) -> ExchangeAdapter:
    """
    Factory function to create exchange adapters.

    Args:
        exchange_name: Name of exchange (binance, okx, bitget)
        api_key: API key
        api_secret: API secret
        password: API password (required for OKX and Bitget)
        testnet: Use testnet/sandbox mode

    Returns:
        ExchangeAdapter instance
    """
    exchange_name = exchange_name.lower()

    if exchange_name == "binance":
        return BinanceAdapter(api_key, api_secret, testnet)
    elif exchange_name == "okx":
        if not password:
            raise ValueError("OKX requires API password")
        return OKXAdapter(api_key, api_secret, password, testnet)
    elif exchange_name == "bitget":
        if not password:
            raise ValueError("Bitget requires API password")
        return BitgetAdapter(api_key, api_secret, password, testnet)
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")
