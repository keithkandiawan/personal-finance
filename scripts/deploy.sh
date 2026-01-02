#!/bin/bash
#
# Personal Finance Tracker - Deployment Script
#
# This script initializes the database and runs all bootstrap scripts
# in the correct order for a fresh deployment.
#
# Usage:
#   ./scripts/deploy.sh                    # Use default database path
#   ./scripts/deploy.sh /path/to/db.db     # Use custom database path
#
# Exit codes:
#   0 - Success
#   1 - Failure (error during deployment)
#   2 - Already deployed (database exists)

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DB_PATH="${1:-data/portfolio.db}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
DATA_DIR="${PROJECT_ROOT}/data"

# Utility functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

separator() {
    echo "======================================================================"
}

# Check if database already exists
check_existing_database() {
    if [ -f "$DB_PATH" ]; then
        log_warning "Database already exists: $DB_PATH"
        read -p "Do you want to reinitialize? This will DELETE all data. [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Deployment cancelled."
            exit 2
        fi
        log_warning "Removing existing database..."
        rm -f "$DB_PATH"
    fi
}

# Create necessary directories
create_directories() {
    log_info "Creating directories..."
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOG_DIR"
    log_success "Directories created"
}

# Check Python installation
check_python() {
    log_info "Checking Python installation..."
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi
    PYTHON_VERSION=$(python3 --version)
    log_success "Found $PYTHON_VERSION"
}

# Check dependencies
check_dependencies() {
    log_info "Checking dependencies..."

    # Try to import required packages
    python3 -c "import dotenv" 2>/dev/null || {
        log_error "python-dotenv not installed"
        log_info "Run: pip install -e ."
        exit 1
    }

    python3 -c "import google.oauth2" 2>/dev/null || {
        log_warning "Google API libraries not installed (optional for Google Sheets)"
        log_info "To enable Google Sheets: pip install -e ."
    }

    log_success "Core dependencies installed"
}

# Initialize database
init_database() {
    separator
    log_info "STEP 1: Initializing database"
    separator

    log_info "Creating database schema at: $DB_PATH"
    python3 scripts/init_db.py "$DB_PATH"

    if [ -f "$DB_PATH" ]; then
        log_success "Database initialized successfully"
    else
        log_error "Database initialization failed"
        exit 1
    fi
}

# Run database migrations
run_migrations() {
    separator
    log_info "STEP 2: Running database migrations"
    separator

    MIGRATIONS_DIR="${PROJECT_ROOT}/sql/migrations"

    if [ ! -d "$MIGRATIONS_DIR" ]; then
        log_warning "No migrations directory found - skipping"
        return 0
    fi

    # Find all .sql migration files and sort them
    MIGRATION_FILES=$(find "$MIGRATIONS_DIR" -name "*.sql" -type f | sort)

    if [ -z "$MIGRATION_FILES" ]; then
        log_info "No migration files found - skipping"
        return 0
    fi

    MIGRATION_COUNT=$(echo "$MIGRATION_FILES" | wc -l | tr -d ' ')
    log_info "Found $MIGRATION_COUNT migration(s) to apply"

    # Run each migration
    while IFS= read -r migration_file; do
        MIGRATION_NAME=$(basename "$migration_file")
        log_info "Applying migration: $MIGRATION_NAME"

        if sqlite3 "$DB_PATH" < "$migration_file" 2>&1; then
            log_success "✓ $MIGRATION_NAME applied"
        else
            log_error "✗ Failed to apply $MIGRATION_NAME"
            exit 1
        fi
    done <<< "$MIGRATION_FILES"

    log_success "All migrations applied successfully"
}

# Bootstrap currencies
bootstrap_currencies() {
    separator
    log_info "STEP 3: Bootstrapping currencies"
    separator

    log_info "Adding base currencies (USD, IDR, BTC, ETH, etc.)..."
    python3 scripts/bootstrap_currencies.py "$DB_PATH"
    log_success "Currencies bootstrapped"
}

# Bootstrap accounts
bootstrap_accounts() {
    separator
    log_info "STEP 4: Bootstrapping accounts"
    separator

    log_info "Adding account types and providers..."
    python3 scripts/bootstrap_accounts.py "$DB_PATH"
    log_success "Accounts bootstrapped"
}

# Bootstrap symbol mappings
bootstrap_symbol_mappings() {
    separator
    log_info "STEP 5: Bootstrapping symbol mappings"
    separator

    log_info "Mapping currencies to TradingView symbols..."
    python3 scripts/bootstrap_symbol_mappings.py "$DB_PATH"
    log_success "Symbol mappings bootstrapped"
}

# Bootstrap blockchain mappings
bootstrap_blockchain_mappings() {
    separator
    log_info "STEP 6: Bootstrapping blockchain mappings"
    separator

    log_info "Configuring EVM networks and contracts..."
    python3 scripts/bootstrap_blockchain_mappings.py "$DB_PATH"
    log_success "Blockchain mappings bootstrapped"
}

# Bootstrap RPC endpoints (optional)
bootstrap_rpc_endpoints() {
    separator
    log_info "STEP 7: Bootstrapping RPC endpoints (optional)"
    separator

    if [ -f "scripts/bootstrap_rpc_endpoints.py" ]; then
        log_info "Configuring default RPC endpoints..."
        python3 scripts/bootstrap_rpc_endpoints.py "$DB_PATH" 2>/dev/null || {
            log_warning "RPC endpoints bootstrap skipped (optional)"
        }
    else
        log_info "No RPC bootstrap script found - skipping"
    fi
}

# Verify deployment
verify_deployment() {
    separator
    log_info "VERIFICATION: Checking database"
    separator

    # Check if database has expected tables
    TABLES=$(sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;" 2>/dev/null || echo "")

    if [ -z "$TABLES" ]; then
        log_error "Database has no tables"
        exit 1
    fi

    log_info "Database tables:"
    echo "$TABLES" | while read -r table; do
        if [ -n "$table" ]; then
            COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo "0")
            echo "  - $table ($COUNT rows)"
        fi
    done

    # Check for critical views
    VIEWS=$(sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='view' AND name IN ('net_worth_summary', 'net_worth_by_currency', 'net_worth_by_asset_class', 'net_worth_history');" 2>/dev/null || echo "")
    VIEW_COUNT=$(echo "$VIEWS" | grep -c "net_worth" || echo "0")

    if [ "$VIEW_COUNT" -eq 4 ]; then
        log_success "All 4 analytics views created"
    else
        log_warning "Analytics views may be incomplete"
    fi
}

# Print next steps
print_next_steps() {
    separator
    log_success "DEPLOYMENT COMPLETE!"
    separator

    echo ""
    echo "Database initialized at: $DB_PATH"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Configure environment variables:"
    echo "   cp .env.example .env"
    echo "   nano .env  # Add your API keys and credentials"
    echo ""
    echo "2. (Optional) Configure Google Sheets:"
    echo "   See: docs/GOOGLE_SHEETS_SETUP.md"
    echo ""
    echo "3. Fetch initial FX rates:"
    echo "   python3 scripts/ingest_fx_rates.py $DB_PATH"
    echo ""
    echo "4. Ingest balances:"
    echo "   python3 scripts/ingest_balances.py --sources all"
    echo ""
    echo "5. Export to Google Sheets (if configured):"
    echo "   python3 scripts/export_to_sheets.py"
    echo ""
    echo "6. Set up cron jobs:"
    echo "   cp cron.example cron.conf"
    echo "   nano cron.conf  # Edit paths"
    echo "   crontab cron.conf"
    echo ""
    separator
}

# Main deployment flow
main() {
    separator
    echo "Personal Finance Tracker - Deployment Script"
    separator
    echo ""

    log_info "Target database: $DB_PATH"
    echo ""

    # Pre-flight checks
    check_existing_database
    create_directories
    check_python
    check_dependencies

    echo ""
    log_info "Starting deployment..."
    echo ""

    # Initialize and bootstrap
    init_database
    run_migrations
    bootstrap_currencies
    bootstrap_accounts
    bootstrap_symbol_mappings
    bootstrap_blockchain_mappings
    bootstrap_rpc_endpoints

    # Verify
    verify_deployment

    # Success
    echo ""
    print_next_steps

    exit 0
}

# Run main function
main
