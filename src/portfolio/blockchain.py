"""
Blockchain Integration

Provides adapters for fetching on-chain balances from EVM-compatible networks.
Uses Web3.py for RPC interactions with Ethereum, Polygon, BSC, Arbitrum, Optimism, Base.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from web3 import Web3

logger = logging.getLogger(__name__)

# Minimal ERC-20 ABI for balance and metadata queries
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


@dataclass
class TokenBalance:
    """Represents a token balance (native or ERC-20)."""

    contract_address: Optional[str]  # None for native tokens
    balance_raw: int  # Raw balance in smallest unit (wei, etc.)
    decimals: int  # Token decimals
    balance: float  # Human-readable balance
    is_native: bool  # True for ETH, BNB, POL, etc.


@dataclass
class TokenMetadata:
    """ERC-20 token metadata."""

    contract_address: str
    symbol: str
    name: str
    decimals: int


class EVMAdapter:
    """Adapter for EVM-compatible blockchain networks."""

    def __init__(self, rpc_url: str, network: str, chain_id: int):
        """
        Initialize EVM adapter.

        Args:
            rpc_url: RPC endpoint URL (Infura, Alchemy, etc.)
            network: Network code (ethereum, polygon, bsc, etc.)
            chain_id: Expected chain ID for verification
        """
        self.rpc_url = rpc_url
        self.network = network
        self.expected_chain_id = chain_id
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))

        # Verify connection
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to {network} at {rpc_url}")

        # Verify chain ID
        actual_chain_id = self.w3.eth.chain_id
        if actual_chain_id != self.expected_chain_id:
            raise ValueError(
                f"{network}: Chain ID mismatch - expected {self.expected_chain_id}, got {actual_chain_id}"
            )

        logger.info(f"Connected to {network} (chain_id: {actual_chain_id})")

    def get_native_balance(self, address: str) -> int:
        """
        Get native token balance (ETH, BNB, POL, etc.) in smallest unit (wei).

        Args:
            address: Wallet address (0x...)

        Returns:
            Balance in wei
        """
        checksum_address = Web3.to_checksum_address(address)
        return self.w3.eth.get_balance(checksum_address)

    def get_erc20_balance(self, token_address: str, wallet_address: str) -> int:
        """
        Get ERC-20 token balance.

        Args:
            token_address: Token contract address
            wallet_address: Wallet address to check

        Returns:
            Balance in token's smallest unit
        """
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address), abi=ERC20_ABI
        )
        return contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()

    def get_token_metadata(self, token_address: str) -> Optional[TokenMetadata]:
        """
        Fetch ERC-20 token metadata (symbol, name, decimals).

        Args:
            token_address: Token contract address

        Returns:
            TokenMetadata or None if failed
        """
        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_address), abi=ERC20_ABI
            )

            symbol = contract.functions.symbol().call()
            name = contract.functions.name().call()
            decimals = contract.functions.decimals().call()

            return TokenMetadata(
                contract_address=token_address.lower(),
                symbol=symbol,
                name=name,
                decimals=decimals,
            )
        except Exception as e:
            logger.debug(f"Failed to fetch metadata for {token_address}: {e}")
            return None

    def discover_erc20_tokens(
        self, wallet_address: str, known_contracts: Dict[str, int]
    ) -> List[TokenBalance]:
        """
        Discover ERC-20 token balances from known contract addresses.

        Args:
            wallet_address: Wallet to check
            known_contracts: Dict of contract_address -> decimals

        Returns:
            List of TokenBalance objects with non-zero balances
        """
        balances = []

        for contract_address, decimals in known_contracts.items():
            try:
                balance_raw = self.get_erc20_balance(contract_address, wallet_address)

                if balance_raw > 0:
                    balance = balance_raw / (10**decimals)
                    balances.append(
                        TokenBalance(
                            contract_address=contract_address.lower(),
                            balance_raw=balance_raw,
                            decimals=decimals,
                            balance=balance,
                            is_native=False,
                        )
                    )
                    logger.info(f"    {contract_address[:10]}...: {balance:.6f}")
            except Exception as e:
                logger.debug(f"    Error checking {contract_address}: {e}")
                continue

        return balances

    def fetch_balances(
        self,
        wallet_address: str,
        native_decimals: int,
        known_erc20_contracts: Dict[str, int],
    ) -> List[TokenBalance]:
        """
        Fetch all balances (native + ERC-20) for a wallet.

        Args:
            wallet_address: Wallet address to scan
            native_decimals: Native token decimals (usually 18)
            known_erc20_contracts: Dict of contract_address -> decimals

        Returns:
            List of TokenBalance objects
        """
        balances = []

        # Get native token balance
        try:
            native_balance_raw = self.get_native_balance(wallet_address)
            if native_balance_raw > 0:
                native_balance = native_balance_raw / (10**native_decimals)
                balances.append(
                    TokenBalance(
                        contract_address=None,
                        balance_raw=native_balance_raw,
                        decimals=native_decimals,
                        balance=native_balance,
                        is_native=True,
                    )
                )
                logger.info(f"    Native token: {native_balance:.6f}")
        except Exception as e:
            logger.error(f"  Failed to fetch native balance: {e}")

        # Get ERC-20 token balances
        if known_erc20_contracts:
            logger.info(f"    Checking {len(known_erc20_contracts)} ERC-20 contracts...")
            erc20_balances = self.discover_erc20_tokens(wallet_address, known_erc20_contracts)
            balances.extend(erc20_balances)

        return balances


class MultiChainAdapter:
    """Multi-chain adapter for fetching balances across multiple EVM networks."""

    def __init__(self, network_configs: Dict[str, Dict]):
        """
        Initialize multi-chain adapter.

        Args:
            network_configs: Dict of network -> {rpc_url, chain_id}
        """
        self.adapters = {}
        for network, config in network_configs.items():
            try:
                self.adapters[network] = EVMAdapter(
                    rpc_url=config["rpc_url"],
                    network=network,
                    chain_id=config["chain_id"],
                )
            except Exception as e:
                logger.error(f"Failed to initialize {network} adapter: {e}")

    def fetch_wallet_balances(
        self,
        wallet_addresses: Dict[str, str],
        known_contracts: Dict[str, Dict[str, int]],
        native_decimals: Dict[str, int],
    ) -> Dict[str, List[TokenBalance]]:
        """
        Fetch balances across all configured networks.

        Args:
            wallet_addresses: Dict of network -> wallet_address
            known_contracts: Dict of network -> dict of {contract_address: decimals}
            native_decimals: Dict of network -> native_token_decimals

        Returns:
            Dict of network -> list of TokenBalance
        """
        all_balances = {}

        for network, address in wallet_addresses.items():
            if network not in self.adapters:
                logger.warning(f"No adapter for {network}, skipping")
                continue

            logger.info(f"  Fetching from {network} ({address[:10]}...)")
            adapter = self.adapters[network]
            native_dec = native_decimals.get(network, 18)
            contracts = known_contracts.get(network, {})

            try:
                balances = adapter.fetch_balances(
                    wallet_address=address,
                    native_decimals=native_dec,
                    known_erc20_contracts=contracts,
                )
                all_balances[network] = balances
                logger.info(f"  ✓ {network}: Found {len(balances)} tokens")
            except Exception as e:
                logger.error(f"  ✗ {network}: Failed to fetch balances - {e}")
                all_balances[network] = []

        return all_balances
