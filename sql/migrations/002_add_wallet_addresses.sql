-- Migration 002: Add Wallet Addresses Support
-- Enables tracking of EVM wallet addresses for on-chain balance ingestion
--
-- Run: sqlite3 data/portfolio.db < sql/migrations/002_add_wallet_addresses.sql

-- Create wallet_addresses table
CREATE TABLE IF NOT EXISTS wallet_addresses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    network             TEXT NOT NULL REFERENCES networks(code),
    address             TEXT NOT NULL,
    label               TEXT,
    is_active           INTEGER DEFAULT 1,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(account_id, network, address),
    CHECK(length(address) = 42 AND address LIKE '0x%')
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_wallet_addresses_account ON wallet_addresses(account_id);
CREATE INDEX IF NOT EXISTS idx_wallet_addresses_network ON wallet_addresses(network);
CREATE INDEX IF NOT EXISTS idx_wallet_addresses_address ON wallet_addresses(network, address);

-- View for active wallet addresses with account and network details
CREATE VIEW IF NOT EXISTS active_wallet_addresses AS
SELECT
    wa.id,
    wa.account_id,
    a.name as account_name,
    wa.network,
    n.name as network_name,
    n.chain_id,
    n.rpc_endpoint,
    wa.address,
    c.code as native_currency,
    wa.label,
    wa.created_at
FROM wallet_addresses wa
INNER JOIN accounts a ON wa.account_id = a.id
INNER JOIN networks n ON wa.network = n.code
INNER JOIN currencies c ON n.native_currency_id = c.id
WHERE wa.is_active = 1 AND a.is_active = 1 AND n.is_active = 1;