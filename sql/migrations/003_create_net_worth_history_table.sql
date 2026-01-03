-- Migration: Replace net_worth_history view with table for daily snapshots
-- Run after 002_add_wallet_addresses.sql

-- ============================================================================
-- 1. Drop existing net_worth_history view
-- ============================================================================

DROP VIEW IF EXISTS net_worth_history;

-- ============================================================================
-- 2. Create net_worth_history table
-- ============================================================================
-- Stores daily snapshots of total net worth (Assets, Liabilities, Net Worth)
-- Populated by daily cron job (scripts/snapshot_net_worth.py)

CREATE TABLE IF NOT EXISTS net_worth_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   DATE NOT NULL UNIQUE,  -- YYYY-MM-DD format
    assets_idr      REAL NOT NULL,         -- Total assets in IDR
    assets_usd      REAL NOT NULL,         -- Total assets in USD
    liabilities_idr REAL NOT NULL,         -- Total liabilities in IDR
    liabilities_usd REAL NOT NULL,         -- Total liabilities in USD
    net_worth_idr   REAL NOT NULL,         -- Net worth in IDR (assets - liabilities)
    net_worth_usd   REAL NOT NULL,         -- Net worth in USD (assets - liabilities)
    num_balances    INTEGER NOT NULL,      -- Number of balance records in snapshot
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast date lookups
CREATE INDEX IF NOT EXISTS idx_net_worth_history_date ON net_worth_history(snapshot_date DESC);

-- ============================================================================
-- 3. Create trigger to update updated_at timestamp
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_net_worth_history_timestamp
AFTER UPDATE ON net_worth_history
FOR EACH ROW
BEGIN
    UPDATE net_worth_history
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;
