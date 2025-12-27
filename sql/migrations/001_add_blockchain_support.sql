-- Migration: Add blockchain and currency relationship support
-- Run after initial schema creation

-- ============================================================================
-- 1. Add parent currency relationship to currencies table
-- ============================================================================
-- Use case: LDBNB → BNB, LDETH → ETH (for price inheritance)

ALTER TABLE currencies ADD COLUMN parent_currency_id INTEGER REFERENCES currencies(id);

-- Index for parent lookups
CREATE INDEX idx_currencies_parent ON currencies(parent_currency_id);

-- ============================================================================
-- 2. Create blockchain contracts table
-- ============================================================================
-- Use case: On-chain data ingestion (wallet balances, DeFi positions)
-- Maps currencies to their contract addresses on various networks

CREATE TABLE IF NOT EXISTS blockchain_contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    currency_id         INTEGER NOT NULL REFERENCES currencies(id) ON DELETE CASCADE,
    network             TEXT NOT NULL,      -- ethereum, polygon, bsc, arbitrum, solana, base, optimism
    contract_address    TEXT,               -- NULL for native tokens (ETH, BNB, SOL, MATIC)
    decimals            INTEGER NOT NULL,   -- 18 for most ERC-20, 6 for USDC, 9 for Solana tokens
    is_native           INTEGER DEFAULT 0,  -- 1 = native token (ETH on Ethereum, BNB on BSC)
    standard            TEXT,               -- ERC-20, BEP-20, SPL, etc.
    is_active           INTEGER DEFAULT 1,
    notes               TEXT,               -- Optional notes (e.g., "bridged from Ethereum")
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- One currency can exist on multiple networks, but only once per network
    UNIQUE(currency_id, network)
);

-- Indexes for blockchain contract lookups
CREATE INDEX idx_blockchain_contracts_currency ON blockchain_contracts(currency_id);
CREATE INDEX idx_blockchain_contracts_network ON blockchain_contracts(network);
CREATE INDEX idx_blockchain_contracts_address ON blockchain_contracts(network, contract_address);

-- ============================================================================
-- 3. Create networks reference table (optional but recommended)
-- ============================================================================
-- Stores network metadata for validation and RPC endpoint management

CREATE TABLE IF NOT EXISTS networks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT NOT NULL UNIQUE,   -- ethereum, polygon, bsc, arbitrum, solana, base
    name                TEXT NOT NULL,          -- Ethereum Mainnet, Polygon, BNB Smart Chain
    chain_id            INTEGER,                -- EVM chain ID (1 for Ethereum, 137 for Polygon, NULL for non-EVM)
    native_currency_id  INTEGER REFERENCES currencies(id),  -- ETH, BNB, MATIC, SOL
    rpc_endpoint        TEXT,                   -- Optional: Your RPC endpoint
    explorer_url        TEXT,                   -- Etherscan, Polygonscan, etc.
    is_evm              INTEGER DEFAULT 1,      -- 1 for EVM chains, 0 for Solana/others
    is_active           INTEGER DEFAULT 1,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- Example Data
-- ============================================================================

-- Example: LDBNB inherits price from BNB
-- UPDATE currencies SET parent_currency_id = (SELECT id FROM currencies WHERE code = 'BNB')
-- WHERE code = 'LDBNB';

-- Example: USDC on Ethereum
-- INSERT INTO blockchain_contracts (currency_id, network, contract_address, decimals, standard)
-- SELECT id, 'ethereum', '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 6, 'ERC-20'
-- FROM currencies WHERE code = 'USDC';

-- Example: Native ETH on Ethereum
-- INSERT INTO blockchain_contracts (currency_id, network, contract_address, decimals, is_native, standard)
-- SELECT id, 'ethereum', NULL, 18, 1, 'Native'
-- FROM currencies WHERE code = 'ETH';

-- ============================================================================
-- Views for convenience
-- ============================================================================

-- View: Currencies with their parent (for price inheritance)
CREATE VIEW IF NOT EXISTS currency_hierarchy AS
SELECT
    c.id,
    c.code,
    c.name,
    c.parent_currency_id,
    p.code as parent_code,
    p.name as parent_name
FROM currencies c
LEFT JOIN currencies p ON c.parent_currency_id = p.id;

-- View: Blockchain contracts with currency info
CREATE VIEW IF NOT EXISTS contract_registry AS
SELECT
    bc.id,
    bc.network,
    bc.contract_address,
    bc.decimals,
    bc.is_native,
    bc.standard,
    c.code as currency_code,
    c.name as currency_name,
    c.type as currency_type_id
FROM blockchain_contracts bc
JOIN currencies c ON bc.currency_id = c.id
WHERE bc.is_active = 1;
