-- Personal Finance Tracker - SQLite Schema
-- Version: 1.0
-- Description: Complete schema with dense indexes for optimal performance

-- ============================================================================
-- LOOKUP TABLES (Dense Indexes)
-- ============================================================================

-- Currency Types (fiat, crypto, stablecoin, stock, etf)
CREATE TABLE IF NOT EXISTS currency_types (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- Account Types (exchange, wallet, bank, cash, brokerage)
CREATE TABLE IF NOT EXISTS account_types (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- Providers (binance, ledger, bca, etc.)
CREATE TABLE IF NOT EXISTS providers (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- ============================================================================
-- MASTER DATA TABLES
-- ============================================================================

-- Currencies (USD, BTC, ETH, AAPL, etc.)
CREATE TABLE IF NOT EXISTS currencies (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    code    TEXT NOT NULL UNIQUE,
    type    INTEGER NOT NULL REFERENCES currency_types(id)
);

-- Symbol Mappings (maps currencies to external data sources)
CREATE TABLE IF NOT EXISTS symbol_mappings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    currency_id     INTEGER NOT NULL REFERENCES currencies(id) ON DELETE CASCADE,
    source          TEXT NOT NULL,  -- 'tradingview', 'binance', 'coinmarketcap', etc.
    symbol          TEXT NOT NULL,  -- 'NASDAQ:AAPL', 'BTCUSDT', etc.
    is_primary      INTEGER DEFAULT 0,  -- 1 = primary source for this currency
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(currency_id, source)
);

-- Accounts (binance_main, ledger_btc, bca_checking, etc.)
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    type            INTEGER NOT NULL REFERENCES account_types(id),
    provider        INTEGER NOT NULL REFERENCES providers(id) ON DELETE RESTRICT,
    notes           TEXT,
    is_active       INTEGER DEFAULT 1,  -- 0 = archived, 1 = active
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- TRANSACTIONAL DATA TABLES
-- ============================================================================

-- FX Rates (latest rates of all currencies to USD)
CREATE TABLE IF NOT EXISTS fx_rates (
    currency_id     INTEGER NOT NULL REFERENCES currencies(id),
    rate            REAL NOT NULL,
    source          TEXT,  -- e.g., 'coinmarketcap', 'exchangerate-api'
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (currency_id)
);

-- Balances (point-in-time snapshots - APPEND ONLY)
CREATE TABLE IF NOT EXISTS balances (
    timestamp       DATETIME NOT NULL,      -- when the balance actually existed
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    currency_id     INTEGER NOT NULL REFERENCES currencies(id),
    quantity        REAL NOT NULL,
    value_idr       REAL,
    value_usd       REAL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,  -- when it was recorded in the system
    PRIMARY KEY (timestamp, account_id, currency_id)
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Balances indexes (critical for time-series queries)
CREATE INDEX IF NOT EXISTS idx_balances_timestamp
    ON balances(timestamp);

CREATE INDEX IF NOT EXISTS idx_balances_account_timestamp
    ON balances(account_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_balances_currency
    ON balances(currency_id);

CREATE INDEX IF NOT EXISTS idx_balances_created_at
    ON balances(created_at);

-- Account indexes
CREATE INDEX IF NOT EXISTS idx_accounts_provider
    ON accounts(provider);

CREATE INDEX IF NOT EXISTS idx_accounts_type
    ON accounts(type);

CREATE INDEX IF NOT EXISTS idx_accounts_is_active
    ON accounts(is_active);

-- Currency indexes
CREATE INDEX IF NOT EXISTS idx_currencies_type
    ON currencies(type);

-- Symbol mappings indexes
CREATE INDEX IF NOT EXISTS idx_symbol_mappings_currency
    ON symbol_mappings(currency_id);

CREATE INDEX IF NOT EXISTS idx_symbol_mappings_source
    ON symbol_mappings(source);

CREATE INDEX IF NOT EXISTS idx_symbol_mappings_primary
    ON symbol_mappings(currency_id, is_primary) WHERE is_primary = 1;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Auto-update fx_rates.updated_at on UPDATE
CREATE TRIGGER IF NOT EXISTS fx_rates_updated_at
AFTER UPDATE ON fx_rates
FOR EACH ROW
BEGIN
    UPDATE fx_rates SET updated_at = CURRENT_TIMESTAMP WHERE currency_id = NEW.currency_id;
END;

-- ============================================================================
-- SEED DATA
-- ============================================================================

-- Initial currency types
INSERT OR IGNORE INTO currency_types (name) VALUES
    ('fiat'),
    ('crypto'),
    ('stablecoin'),
    ('stock'),
    ('etf');

-- Initial account types
INSERT OR IGNORE INTO account_types (name) VALUES
    ('exchange'),
    ('wallet'),
    ('bank'),
    ('cash'),
    ('brokerage');

-- ============================================================================
-- VIEWS FOR REPORTING
-- ============================================================================

-- Latest balances per account and currency
CREATE VIEW IF NOT EXISTS latest_balances AS
SELECT
    b.account_id,
    a.name as account_name,
    b.currency_id,
    c.code as currency_code,
    b.quantity,
    b.value_idr,
    b.value_usd,
    b.timestamp
FROM balances b
INNER JOIN accounts a ON b.account_id = a.id
INNER JOIN currencies c ON b.currency_id = c.id
WHERE (b.account_id, b.currency_id, b.timestamp) IN (
    SELECT account_id, currency_id, MAX(timestamp)
    FROM balances
    GROUP BY account_id, currency_id
)
AND a.is_active = 1;

-- Net worth summary by currency
CREATE VIEW IF NOT EXISTS net_worth_by_currency AS
SELECT
    c.code as currency_code,
    ct.name as currency_type,
    SUM(lb.quantity) as total_quantity,
    SUM(lb.value_idr) as total_value_idr,
    SUM(lb.value_usd) as total_value_usd
FROM latest_balances lb
INNER JOIN currencies c ON lb.currency_id = c.id
INNER JOIN currency_types ct ON c.type = ct.id
GROUP BY c.code, ct.name
ORDER BY total_value_usd DESC;

-- Net worth summary by account provider
CREATE VIEW IF NOT EXISTS net_worth_by_provider AS
SELECT
    p.name as provider_name,
    SUM(lb.value_idr) as total_value_idr,
    SUM(lb.value_usd) as total_value_usd,
    COUNT(DISTINCT lb.account_id) as num_accounts
FROM latest_balances lb
INNER JOIN accounts a ON lb.account_id = a.id
INNER JOIN providers p ON a.provider = p.id
GROUP BY p.name
ORDER BY total_value_usd DESC;

-- Net worth summary by asset class
CREATE VIEW IF NOT EXISTS net_worth_by_asset_class AS
SELECT
    ct.name as asset_class,
    SUM(lb.value_idr) as total_value_idr,
    SUM(lb.value_usd) as total_value_usd,
    COUNT(DISTINCT lb.currency_id) as num_currencies
FROM latest_balances lb
INNER JOIN currencies c ON lb.currency_id = c.id
INNER JOIN currency_types ct ON c.type = ct.id
GROUP BY ct.name
ORDER BY total_value_usd DESC;

-- Historical net worth over time (daily snapshots)
CREATE VIEW IF NOT EXISTS net_worth_history AS
SELECT
    DATE(b.timestamp) as date,
    SUM(b.value_idr) as total_value_idr,
    SUM(b.value_usd) as total_value_usd
FROM balances b
INNER JOIN accounts a ON b.account_id = a.id
WHERE a.is_active = 1
GROUP BY DATE(b.timestamp)
ORDER BY date;

-- Stale FX rates (older than 24 hours)
CREATE VIEW IF NOT EXISTS stale_fx_rates AS
SELECT
    c.code as currency_code,
    ct.name as currency_type,
    fx.rate,
    fx.source,
    fx.updated_at,
    ROUND((julianday('now') - julianday(fx.updated_at)) * 24, 1) as hours_since_update
FROM fx_rates fx
INNER JOIN currencies c ON fx.currency_id = c.id
INNER JOIN currency_types ct ON c.type = ct.id
WHERE (julianday('now') - julianday(fx.updated_at)) * 24 > 24
ORDER BY fx.updated_at ASC;
