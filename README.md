# Personal Finance Tracker

A low-maintenance, reliable personal portfolio tracking system designed for long-term use on minimal infrastructure.

## Design Principles

- **SQLite as single source of truth** - All data lives in one database
- **Spreadsheets as UI only** - Human interaction via Google Sheets/Excel
- **Append-only data model** - Never overwrite historical financial data
- **Idempotent ingestion** - Scripts can run multiple times safely
- **Low memory footprint** - Runs comfortably on ~300MB RAM (EC2 nano)

## Features

- Track multiple asset classes: crypto, stocks, ETFs, stablecoins, fiat
- Support multiple data sources (TradingView, Binance, CoinMarketCap, etc.)
- Automatic price updates via scheduled jobs
- Historical net worth tracking
- Asset allocation reporting by provider, currency, and asset class
- Spreadsheet-based manual data entry via Google Sheets

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repo-url>
cd personal-finance

# Install dependencies
pip install -e .
```

### 2. Initialize Database

**Option 1: Quick Setup (Recommended)**

Use the deployment script to initialize everything in one command:

```bash
# Initialize database and run all bootstrap scripts
./scripts/deploy.sh

# Or specify custom database path
./scripts/deploy.sh /path/to/portfolio.db
```

This automatically:
- Creates the database with complete schema
- Runs all database migrations
- Bootstraps currencies (USD, BTC, ETH, etc.)
- Bootstraps account types and providers
- Configures TradingView symbol mappings
- Sets up blockchain network configurations
- Verifies the deployment

**Option 2: Manual Setup**

```bash
# Create the database with schema
python scripts/init_db.py data/portfolio.db

# Run migrations
sqlite3 data/portfolio.db < sql/migrations/001_add_blockchain_support.sql
sqlite3 data/portfolio.db < sql/migrations/002_add_wallet_addresses.sql

# Bootstrap currencies
python scripts/bootstrap_currencies.py data/portfolio.db

# Bootstrap accounts
python scripts/bootstrap_accounts.py data/portfolio.db

# Bootstrap symbol mappings
python scripts/bootstrap_symbol_mappings.py data/portfolio.db

# Bootstrap blockchain mappings
python scripts/bootstrap_blockchain_mappings.py data/portfolio.db
```

The database includes:
- 9 tables with proper foreign keys
- 15+ indexes for performance
- 6 reporting views
- Seed data for currency/account types

### 3. Run Example

```bash
# Add sample currencies and fetch prices
python scripts/example_setup.py data/portfolio.db
```

This demonstrates:
- Adding currencies (stocks, crypto, ETFs)
- Mapping to TradingView symbols
- Fetching current prices

## Project Structure

```
personal-finance/
├── pyproject.toml          # Project metadata and dependencies
├── README.md               # This file
├── PLAN.md                 # Detailed project specification
├── .gitignore             # Git ignore rules
│
├── src/portfolio/          # Main Python package
│   ├── __init__.py
│   └── tradingview.py     # TradingView price fetcher
│
├── scripts/                # Executable scripts
│   ├── init_db.py         # Database initialization
│   └── example_setup.py   # Example usage
│
├── sql/                    # SQL schemas
│   └── schema.sql         # Complete database schema
│
├── data/                   # Database files (gitignored)
│   └── portfolio.db
│
└── tests/                  # Tests (future)
    └── __init__.py
```

## Database Schema

### Lookup Tables (Dense Indexes)
- `currency_types` - fiat, crypto, stablecoin, stock, etf
- `account_types` - exchange, wallet, bank, cash, brokerage
- `providers` - binance, ledger, bca, etc.

### Master Data
- `currencies` - USD, BTC, AAPL, etc.
- `symbol_mappings` - Maps currencies to external data sources
- `accounts` - Your actual accounts with balances

### Transactional Data
- `fx_rates` - Latest exchange rates (to USD)
- `balances` - Point-in-time snapshots (append-only)

### Views
- `latest_balances` - Most recent balance per account/currency
- `net_worth_by_currency` - Total holdings by currency
- `net_worth_by_provider` - Total holdings by provider
- `net_worth_by_asset_class` - Total holdings by asset class
- `net_worth_history` - Daily net worth over time
- `stale_fx_rates` - Rates older than 24 hours

## Usage Examples

### Adding a New Currency

```python
import sqlite3

conn = sqlite3.connect('data/portfolio.db')

# Add a stock
conn.execute("""
    INSERT INTO currencies (code, type)
    VALUES ('GOOGL', (SELECT id FROM currency_types WHERE name='stock'))
""")
currency_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

# Map to TradingView
conn.execute("""
    INSERT INTO symbol_mappings (currency_id, source, symbol, is_primary)
    VALUES (?, 'tradingview', 'NASDAQ:GOOGL', 1)
""", (currency_id,))

conn.commit()
conn.close()
```

### Fetching Prices from TradingView

```python
from portfolio.tradingview import fetch_and_update_prices

# Fetch and update all prices
updated_count = fetch_and_update_prices('data/portfolio.db')
print(f"Updated {updated_count} prices")
```

### Checking for Stale Rates

```python
from portfolio.tradingview import check_stale_rates

stale = check_stale_rates('data/portfolio.db', hours=24)
for rate in stale:
    print(f"{rate['currency_code']}: {rate['hours_old']}h old")
```

### Querying Net Worth

```sql
-- Current net worth by asset class
SELECT * FROM net_worth_by_asset_class;

-- Historical net worth
SELECT * FROM net_worth_history
WHERE date >= date('now', '-30 days')
ORDER BY date;

-- Latest balances
SELECT
    account_name,
    currency_code,
    quantity,
    value_usd
FROM latest_balances
ORDER BY value_usd DESC;
```

## Scheduling (Production)

### FX Rate Updates

The FX ingestion script fetches current exchange rates from TradingView:

```bash
# Run manually
python scripts/ingest_fx_rates.py data/portfolio.db

# Check logs
tail -f logs/fx_rates_$(date +%Y%m).log
```

**Features:**
- Lock file prevents concurrent runs
- Monthly log rotation
- Validates database before running
- Reports stale rates (>24h old)
- Exit codes: 0=success, 1=failure, 2=already running

### Cron Setup

```bash
# Copy example config
cp cron.example cron.conf

# Edit paths
nano cron.conf

# Install crontab
crontab cron.conf

# Example: Update FX rates daily at 9 AM
0 9 * * * cd /path/to/personal-finance && python scripts/ingest_fx_rates.py data/portfolio.db
```

See `cron.example` for complete scheduling examples.

### Exporting Analytics to Google Sheets

Export database views to Google Sheets for visualization and dashboards:

```bash
# Run manually
python scripts/export_to_sheets.py data/portfolio.db

# Check logs
tail -f logs/export_$(date +%Y%m).log
```

**Exported tabs:**
- `Summary` - Assets, Liabilities, Net Worth totals
- `By Asset Class` - Breakdown by crypto/stocks/fiat/etc.
- `By Currency` - Holdings per currency
- `History` - Daily net worth time series

**Features:**
- Overwrites existing data (preserves charts)
- Automatic timestamp footer
- Lock file prevents concurrent runs
- Formatted numbers with 2 decimal places
- Exit codes: 0=success, 1=failure, 2=already running

**Setup:**
```bash
# Option 1: Use same sheet as balance imports
# (no additional config needed, uses GOOGLE_SHEET_ID)

# Option 2: Use separate sheet for exports (recommended)
echo "EXPORT_SHEET_ID=your-export-sheet-id" >> .env

# Share sheet with service account (Editor permission required)
# See docs/GOOGLE_SHEETS_SETUP.md
```

**Scheduling:**
```bash
# Export every 6 hours (5 minutes after balance ingestion)
5 */6 * * * cd /path && python scripts/export_to_sheets.py >> logs/export.log 2>&1
```

## Development

### Install Dev Dependencies

```bash
pip install -e ".[dev]"
```

### Code Formatting

```bash
# Format code with black
black src/ scripts/

# Lint with ruff
ruff check src/ scripts/
```

### Running Tests

```bash
pytest tests/
```

## Security Notes

- Store API keys in environment variables or `.env` file (chmod 0600)
- No public HTTP endpoints required
- No inbound ports needed
- Encrypt backups before leaving VM

## Support

For issues or questions, see `PLAN.md` for detailed specifications.

## License

Personal use only.
