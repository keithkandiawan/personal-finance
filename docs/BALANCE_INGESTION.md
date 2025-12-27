# Balance Ingestion Guide

This document explains how to ingest balances from various sources into the portfolio database.

## Overview

The portfolio system tracks balances from three sources:
1. **Exchanges** (Binance, OKX, Bitget via CCXT)
2. **On-Chain Wallets** (EVM chains: Ethereum, Polygon, BSC, Arbitrum, Optimism, Base)
3. **Fiat Accounts** (Google Sheets)

## Recommended Workflow

### Use the Unified Script (Recommended)

The unified script `scripts/ingest_balances.py` handles all sources and correctly manages zero-balance tracking:

```bash
# Ingest from ALL sources (recommended - creates atomic snapshot)
python scripts/ingest_balances.py --sources all

# Or ingest from specific source only
python scripts/ingest_balances.py --sources exchanges
python scripts/ingest_balances.py --sources wallets
python scripts/ingest_balances.py --sources fiat
```

**Key Features:**
- Single atomic snapshot when using `--sources all`
- Zero-balance logic ONLY when running all sources (prevents stale balances)
- No zero-balance logic when running individual sources (prevents incorrect zeros)

### Individual Scripts (Legacy)

The individual scripts are still available but DON'T use zero-balance logic:

```bash
# Exchange balances only (no zero-balance logic)
python scripts/ingest_crypto_balances.py

# On-chain wallet balances only (no zero-balance logic)
python scripts/ingest_onchain_balances.py

# Fiat balances only (no zero-balance logic)
python scripts/ingest_fiat_balances.py
```

**Use these when:**
- You only want to update one specific source
- You're testing a new exchange or wallet
- You're debugging a specific integration

**DO NOT use these when:**
- You want accurate zero-balance tracking
- You've sold/transferred assets and want to record zeros
- You want a complete snapshot

## Zero-Balance Logic Explained

### What is it?

Zero-balance logic explicitly records when a previously held asset reaches zero quantity. This prevents the `latest_balances` view from showing stale balances.

**Example:**
- Day 1: You hold 100 USDC on Binance
- Day 2: You transfer all USDC to a wallet
- Without zero-balance: `latest_balances` still shows 100 USDC on Binance (WRONG!)
- With zero-balance: A new record with 0 USDC on Binance is created (CORRECT!)

### Why only with `--sources all`?

Running individual scripts creates an **incomplete picture**:

**Bad example:**
```bash
# Run exchange script (sees no USDC on exchanges)
python scripts/ingest_crypto_balances.py
# → Would add zero for USDC if it had zero-balance logic

# Run wallet script later (sees USDC in wallet)
python scripts/ingest_onchain_balances.py
# → But zero was already recorded!
```

**Good example:**
```bash
# Run unified script with all sources
python scripts/ingest_balances.py --sources all
# → Sees complete picture: no USDC on exchanges, yes USDC in wallet
# → Only adds zero for assets truly gone from ALL sources
```

## Cron Setup

### Option 1: Unified Script (Recommended)

```cron
# Every 4 hours - complete snapshot with zero-balance tracking
0 */4 * * * cd /path/to/personal-finance && python scripts/ingest_balances.py --sources all >> logs/balances.log 2>&1
```

### Option 2: Separate Schedules

```cron
# Exchange balances every 4 hours
0 */4 * * * cd /path/to/personal-finance && python scripts/ingest_crypto_balances.py >> logs/crypto.log 2>&1

# On-chain balances every 6 hours
0 */6 * * * cd /path/to/personal-finance && python scripts/ingest_onchain_balances.py >> logs/onchain.log 2>&1

# Fiat balances daily at 8 AM
0 8 * * * cd /path/to/personal-finance && python scripts/ingest_fiat_balances.py >> logs/fiat.log 2>&1

# Weekly complete snapshot with zero-balance (Sunday at midnight)
0 0 * * 0 cd /path/to/personal-finance && python scripts/ingest_balances.py --sources all >> logs/weekly_snapshot.log 2>&1
```

## Monitoring

Check the latest balances:

```sql
SELECT account_name, currency_code, quantity, value_usd
FROM latest_balances
WHERE quantity > 0
ORDER BY value_usd DESC;
```

Check for assets with zero balances (recently sold):

```sql
SELECT account_name, currency_code, timestamp
FROM balances
WHERE quantity = 0
ORDER BY timestamp DESC
LIMIT 20;
```

## Troubleshooting

### Issue: Stale balances appearing in latest_balances

**Cause:** Individual scripts running without zero-balance logic

**Solution:** Run the unified script with all sources:
```bash
python scripts/ingest_balances.py --sources all
```

### Issue: Incorrect zero balances

**Cause:** Old individual scripts with zero-balance logic (pre-refactor)

**Solution:** Make sure you've pulled the latest code where individual scripts have zero-balance logic removed

### Issue: Exchange API rate limits

**Cause:** Running scripts too frequently

**Solution:**
- Reduce cron frequency
- Use `--sources exchanges` only when needed
- Check exchange API rate limits

### Issue: RPC rate limits (wallets)

**Cause:** Too many on-chain balance queries

**Solution:**
- Reduce wallet script frequency
- Use Infura/Alchemy paid tier
- Implement Multicall3 batching (future optimization)

## Architecture Notes

### Why Three Separate Modules?

Each source has different characteristics:

1. **Exchanges** (`portfolio.exchanges`):
   - Uses CCXT library
   - API keys required
   - Fast (< 1 second per exchange)
   - Rate limits: ~1 req/sec per exchange

2. **Wallets** (`portfolio.blockchain`):
   - Uses Web3.py
   - RPC endpoints required
   - Slower (1-2 seconds per network)
   - Rate limits: Depends on provider

3. **Fiat** (`Google Sheets`):
   - Manual entry
   - No API keys for balances (just Google Sheets API)
   - Fast (< 1 second)
   - No rate limits

### Database Schema

All balances stored in single `balances` table:

```sql
CREATE TABLE balances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    currency_id     INTEGER NOT NULL REFERENCES currencies(id),
    quantity        REAL NOT NULL,
    value_usd       REAL,
    value_idr       REAL
);
```

The `latest_balances` view shows the most recent snapshot:

```sql
CREATE VIEW latest_balances AS
SELECT
    b.account_id,
    a.name as account_name,
    b.currency_id,
    c.code as currency_code,
    b.quantity,
    b.value_usd,
    b.value_idr,
    b.timestamp
FROM balances b
INNER JOIN accounts a ON b.account_id = a.id
INNER JOIN currencies c ON b.currency_id = c.id
WHERE b.timestamp = (
    SELECT MAX(timestamp)
    FROM balances b2
    WHERE b2.account_id = b.account_id
    AND b2.currency_id = b.currency_id
);
```

### Zero-Balance Implementation

Only in `scripts/ingest_balances.py` when `--sources all`:

```python
def add_zero_balances_for_sold_assets(balances, db_path):
    # Get current holdings
    current = {(b['account_id'], b['currency_id']) for b in balances}

    # Get historical holdings
    historical = query("SELECT DISTINCT account_id, currency_id FROM latest_balances WHERE quantity > 0")

    # Find assets that were held before but not in current snapshot
    sold = historical - current

    # Add explicit zeros
    for account_id, currency_id in sold:
        balances.append({
            'account_id': account_id,
            'currency_id': currency_id,
            'quantity': 0.0,
            'value_usd': 0.0,
            'value_idr': 0.0,
        })

    return balances
```
