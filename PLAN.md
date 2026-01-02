Personal Portfolio Tracker – AI Agent Project Brief

1. Objective

Build a low-maintenance, reliable, personal portfolio tracking system with:
	•	SQLite as the single source of truth
	•	Python for ingestion and reporting
	•	Spreadsheet (Google Sheets / Excel) as the only human-facing UI
	•	always-on execution via a small EC2 nano VM

The system must support crypto assets, manual balance tracking via Google Sheets, and FX rates, while remaining simple enough for non-technical users to interact with safely.

This document defines the scope, architecture, constraints, and concrete tasks for an AI agent working on this project.

⸻

2. Non-Goals (Explicit)

The agent must not:
	•	Build a full web application
	•	Use Streamlit or any long-running web server on the VM
	•	Use Google Sheets as a primary datastore
	•	Optimize for real-time or high-frequency updates
	•	Introduce cloud-native complexity (Lambda, DynamoDB, etc.)

⸻

3. Core Design Principles
	1.	SQLite is the source of truth
All automated and manual data ultimately lives in SQLite.
	2.	Spreadsheets are UI only
Humans edit spreadsheets; scripts import/export data.
	3.	Append-only data model
Never overwrite historical financial data.
	4.	Idempotent ingestion
Scripts may run late, early, or multiple times without corruption.
	5.	Low memory footprint
Must run comfortably on ~300 MB available RAM.

⸻

4. System Architecture (High Level)

[Crypto APIs]        [FX APIs]
     │                   │
     └──────┐      ┌─────┘
            ▼      ▼
        Python ingestion scripts
                   │
                   ▼
               SQLite DB
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
  CSV exports         Validation / reports
         │
         ▼
  Google Sheets / Excel


⸻

5. Data Ownership Rules

Data Type	Source of Truth	Human Editable
Crypto balances	SQLite	No
Crypto prices	SQLite	No
Sheet balances (fiat & crypto)	Spreadsheet → SQLite	Yes (via Google sheet)
FX rates	SQLite	No
Reports	Spreadsheet	Yes (formulas only)


⸻

6. Database Schema (Authoritative)

6.1 currencies

id     INTEGER PRIMARY KEY AUTOINCREMENT  -- dense index
code   TEXT NOT NULL UNIQUE               -- USD, IDR, BTC, ETH
type   INTEGER NOT NULL REFERENCES currency_types(id)

6.2 currency_types

id     INTEGER PRIMARY KEY AUTOINCREMENT  -- dense index
name   TEXT NOT NULL UNIQUE               -- fiat | crypto | stablecoin | stock | etf

6.3 symbol_mappings

Maps currencies to external data source symbols (TradingView, Binance, etc.)

id              INTEGER PRIMARY KEY AUTOINCREMENT
currency_id     INTEGER NOT NULL REFERENCES currencies(id) ON DELETE CASCADE
source          TEXT NOT NULL                      -- 'tradingview', 'binance', 'coinmarketcap'
symbol          TEXT NOT NULL                      -- 'NASDAQ:AAPL', 'BTCUSDT', 'ICE:USDIDR', etc.
is_inverted     INTEGER DEFAULT 0                  -- 1 = invert rate (for USD/XXX pairs)
is_primary      INTEGER DEFAULT 0                  -- 1 = primary source for this currency
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
UNIQUE(currency_id, source)

Examples:
  AAPL: symbol='NASDAQ:AAPL', is_inverted=0 (price is USD per share)
  BTC:  symbol='BINANCE:BTCUSDT', is_inverted=0 (price is USD per BTC)
  IDR:  symbol='ICE:USDIDR', is_inverted=1 (TradingView shows USD/IDR, we invert to get IDR rate)

6.4 accounts
--------
id              INTEGER PRIMARY KEY AUTOINCREMENT  -- dense index
name            TEXT NOT NULL UNIQUE               -- binance_main, ledger_btc
type            INTEGER NOT NULL REFERENCES account_types(id)
provider        INTEGER NOT NULL REFERENCES providers(id) ON DELETE RESTRICT
notes           TEXT
is_active       INTEGER DEFAULT 1                  -- 0 = archived, 1 = active
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP

6.5 account_types
id     INTEGER PRIMARY KEY AUTOINCREMENT  -- dense index
name   TEXT NOT NULL UNIQUE               -- Assets: exchange | wallet | bank | cash | brokerage
                                          -- Liabilities: loan | credit_card | payable

6.6 providers
id     INTEGER PRIMARY KEY AUTOINCREMENT  -- dense index
name   TEXT NOT NULL UNIQUE               -- binance, ledger, bca

6.7 fx_rates

Latest FX Snapshots, will be replaced by new data. All rates normalized to USD.
currency_id     INTEGER NOT NULL REFERENCES currencies(id)
rate            REAL NOT NULL                      -- How many USD per 1 unit of currency
source          TEXT                               -- e.g., 'tradingview', 'coinmarketcap'
updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
PRIMARY KEY (currency_id)

Examples:
  USD:  rate=1.0       (base currency)
  IDR:  rate=0.0000625 (if TradingView USD/IDR=16000, inverted via symbol mapping)
  BTC:  rate=45000
  AAPL: rate=195

Note: For USD/XXX pairs (like ICE:USDIDR), set is_inverted=1 in symbol_mappings to get XXX rate

6.8 balances

Point-in-time snapshots.

timestamp       DATETIME NOT NULL                  -- when the balance actually existed
account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT
currency_id     INTEGER NOT NULL REFERENCES currencies(id)
quantity        REAL NOT NULL
value_idr       REAL
value_usd       REAL
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP -- when it was recorded in the system
PRIMARY KEY (timestamp, account_id, currency_id)

-- Indexes for performance
CREATE INDEX idx_balances_timestamp ON balances(timestamp);
CREATE INDEX idx_balances_account_timestamp ON balances(account_id, timestamp);
CREATE INDEX idx_balances_currency ON balances(currency_id);

⸻

7. Ingestion Responsibilities

7.1 Crypto Ingestion Script
	•	Fetch balances via API
	•	Fetch prices (or use FX table)
	•	Insert snapshot
	•	Never update existing rows

7.2 FX Ingestion Script
	•	Fetch daily FX rates
	•	Store source
	•	Append only

7.3 Sheet Import Script
	•	Read spreadsheet (Via google Sheets API)
	•	Validate:
	•	Non-negative balances
	•	Monotonic dates per account
	•	Insert snapshot rows

⸻

8. Reporting & Export

The agent should generate:
- Report for Total Networth
- Historical Net Worth Over time (ALL TIME)
- Asset Allocation Report (Breakdown by Asset Class & by Account Provider)


⸻

9. Scheduling Model
	•	Execution via cron or launchd
	•	Scripts must:
	•	Exit cleanly

Missed runs are acceptable.

⸻

10. Security Constraints
	•	API keys stored as environment variables or .env (0600)
	•	No public HTTP endpoints
	•	No inbound ports required
	
⸻

11. Success Criteria

The project is considered successful when:
	•	Crypto balances update automatically
	•	Sheet balances are easy to maintain via spreadsheet
	•	Net worth can be recomputed for any historical date
	•	VM memory usage remains stable
	•	Non-technical users never touch the database or scripts

⸻

12. Deliverables for the AI Agent
	1.	SQLite schema creation script
	2.	Python ingestion scripts (crypto, FX, sheet)
	3.	Validation logic
	4.	CSV export scripts
	5.	Minimal README for human operation

⸻

13. Final Instruction to the AI Agent

Optimize for simplicity, determinism, and long-term maintainability.

When in doubt:
	•	Prefer SQLite over services
	•	Prefer batch jobs over daemons
	•	Prefer clarity over cleverness