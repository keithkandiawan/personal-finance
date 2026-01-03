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

# Check OS is Linux
check_os() {
    log_info "Checking operating system..."

    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        log_error "This deployment script only supports Linux"
        log_error "Detected OS: $OSTYPE"
        echo ""
        log_info "For macOS or other systems:"
        log_info "  1. Manually run bootstrap scripts"
        log_info "  2. Set up scheduling manually with launchd (macOS)"
        echo ""
        exit 1
    fi

    log_success "Running on Linux"
}

# Check systemd availability
check_systemd() {
    log_info "Checking systemd availability..."

    if ! command -v systemctl &> /dev/null; then
        log_error "systemd is not available on this system"
        log_info "This script requires systemd for service management"
        exit 1
    fi

    log_success "systemd is available"
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

# Confirm Python environment
confirm_python_environment() {
    separator
    log_info "Python Environment Confirmation"
    separator

    # Detect current Python
    PYTHON_PATH=$(which python3 2>/dev/null || which python 2>/dev/null || echo "")

    if [ -z "$PYTHON_PATH" ]; then
        log_error "Python not found in PATH"
        exit 1
    fi

    echo ""
    log_info "Detected Python environment:"
    echo "  Path:    $PYTHON_PATH"

    # Get version
    PYTHON_VERSION=$($PYTHON_PATH --version 2>&1)
    echo "  Version: $PYTHON_VERSION"

    # Test Python can import required packages
    echo ""
    log_info "Checking dependencies..."
    if ! $PYTHON_PATH -c "import dotenv" 2>/dev/null; then
        log_error "python-dotenv not found in this environment"
        log_error "Please install dependencies first: pip install -e ."
        exit 1
    fi
    log_success "✓ Required packages installed"

    # Ask for confirmation
    echo ""
    log_warning "IMPORTANT: This Python environment will be used for all automated jobs."
    echo ""
    read -p "Continue with this Python environment? [y/N] " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        log_info "Deployment cancelled."
        echo ""
        log_info "To use a different Python:"
        echo "  1. Activate your desired Python environment"
        echo "  2. Re-run this script: ./scripts/deploy.sh"
        echo ""
        exit 0
    fi

    log_success "✓ Python environment confirmed: $PYTHON_PATH"
}

# Install systemd timers
install_systemd_timers() {
    separator
    log_info "STEP 8: Installing systemd timers (optional)"
    separator

    echo ""
    log_info "This will install a daily automated update sequence:"
    echo "  9:00 AM - Complete portfolio update (all 4 steps)"
    echo "    → Update FX rates"
    echo "    → Ingest balances (all sources)"
    echo "    → Create net worth snapshot"
    echo "    → Export to Google Sheets"
    echo ""
    log_info "All steps run sequentially in correct dependency order"
    echo ""

    read -p "Do you want to install systemd timers? [y/N] " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Skipping systemd installation"
        echo ""
        log_warning "You can set up automation later by re-running this script"
        return 0
    fi

    # Create systemd user directory
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_USER_DIR"

    # Create environment file for systemd
    ENV_FILE="${PROJECT_ROOT}/.env.systemd"
    log_info "Creating systemd environment file..."

    # Get PATH from conda if applicable
    PYTHON_DIR=$(dirname "$PYTHON_PATH")
    PYTHON_BIN_DIR=$(dirname "$PYTHON_DIR")/bin

    cat > "$ENV_FILE" << EOF
# Systemd environment file for portfolio tracker
# Auto-generated by deploy.sh

PYTHON_PATH=$PYTHON_PATH
PROJECT_DIR=$PROJECT_ROOT
PATH=$PYTHON_DIR:$PYTHON_BIN_DIR:/usr/local/bin:/usr/bin:/bin
HOME=$HOME
USER=$USER
EOF

    log_success "✓ Environment file: $ENV_FILE"

    # Create systemd service file
    SERVICE_FILE="$SYSTEMD_USER_DIR/portfolio-update.service"
    log_info "Creating systemd service..."

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Portfolio Tracker Daily Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$ENV_FILE

# Run all 4 steps sequentially
ExecStart=/bin/bash -c '\
  \$PYTHON_PATH scripts/ingest_fx_rates.py data/portfolio.db && \
  sleep 10 && \
  \$PYTHON_PATH scripts/ingest_balances.py --sources all && \
  sleep 10 && \
  \$PYTHON_PATH scripts/snapshot_net_worth.py && \
  sleep 10 && \
  \$PYTHON_PATH scripts/export_to_sheets.py'

# Logging
StandardOutput=append:/var/log/portfolio/update.log
StandardError=append:/var/log/portfolio/update.log

# Security
PrivateTmp=yes
NoNewPrivileges=yes

# Restart on failure
Restart=on-failure
RestartSec=300

[Install]
WantedBy=default.target
EOF

    log_success "✓ Service file: $SERVICE_FILE"

    # Create systemd timer file
    TIMER_FILE="$SYSTEMD_USER_DIR/portfolio-update.timer"
    log_info "Creating systemd timer..."

    cat > "$TIMER_FILE" << EOF
[Unit]
Description=Run portfolio update daily at 9 AM
Requires=portfolio-update.service

[Timer]
OnCalendar=daily
OnCalendar=*-*-* 09:00:00
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

    log_success "✓ Timer file: $TIMER_FILE"

    # Create log directory
    log_info "Setting up logging..."

    if [ -w /var/log ]; then
        # Can write to /var/log directly
        sudo mkdir -p /var/log/portfolio
        sudo chown $USER:$USER /var/log/portfolio
        log_success "✓ Log directory: /var/log/portfolio/"
    else
        # Fall back to project logs directory
        log_warning "Cannot write to /var/log (need sudo)"
        log_info "Using project logs directory instead"

        # Update service file to use project logs
        sed -i "s|/var/log/portfolio/|$LOG_DIR/|g" "$SERVICE_FILE"
    fi

    # Reload systemd and enable timer
    log_info "Enabling systemd timer..."

    systemctl --user daemon-reload
    systemctl --user enable portfolio-update.timer
    systemctl --user start portfolio-update.timer

    if systemctl --user is-active --quiet portfolio-update.timer; then
        log_success "✓ Systemd timer installed and running"
        echo ""
        log_info "Timer status:"
        systemctl --user status portfolio-update.timer --no-pager | head -n 10
        echo ""
        log_info "Next run:"
        systemctl --user list-timers portfolio-update.timer --no-pager
    else
        log_error "✗ Failed to start systemd timer"
        return 1
    fi

    echo ""
    log_info "Useful commands:"
    echo "  View logs:    journalctl --user -u portfolio-update.service -f"
    echo "  Check status: systemctl --user status portfolio-update.timer"
    echo "  Run now:      systemctl --user start portfolio-update.service"
    echo "  Disable:      systemctl --user disable portfolio-update.timer"
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

    # Check for critical views/tables
    log_info "Checking analytics views/tables..."

    # Check if net_worth_history is a table or view
    NWH_TYPE=$(sqlite3 "$DB_PATH" "SELECT type FROM sqlite_master WHERE name='net_worth_history';" 2>/dev/null || echo "")

    if [ "$NWH_TYPE" = "table" ]; then
        log_success "✓ net_worth_history table exists (migration 003 applied)"
    elif [ "$NWH_TYPE" = "view" ]; then
        log_warning "⚠ net_worth_history is still a view (migration 003 not applied?)"
    else
        log_warning "⚠ net_worth_history not found"
    fi

    # Check other critical views
    VIEWS=$(sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='view' AND name IN ('net_worth_summary', 'net_worth_by_currency', 'net_worth_by_asset_class', 'latest_balances');" 2>/dev/null || echo "")
    VIEW_COUNT=$(echo "$VIEWS" | wc -w | tr -d ' ')

    if [ "$VIEW_COUNT" -ge 3 ]; then
        log_success "✓ Analytics views created"
    else
        log_warning "⚠ Some analytics views may be missing"
    fi
}

# Print next steps
print_next_steps() {
    separator
    log_success "DEPLOYMENT COMPLETE!"
    separator

    echo ""
    echo "✓ Database initialized at: $DB_PATH"
    echo "✓ Database migrations applied (including migration 003)"
    echo "✓ Bootstrap data loaded"
    echo "✓ Python configured: $PYTHON_PATH"

    if systemctl --user is-active --quiet portfolio-update.timer 2>/dev/null; then
        echo "✓ Systemd timer installed and active"
    fi

    echo ""
    echo "Next steps to start using the system:"
    echo ""
    echo "1. Configure environment variables:"
    echo "   cp .env.example .env"
    echo "   nano .env  # Add your API keys and credentials"
    echo ""
    echo "2. (Optional) Configure Google Sheets:"
    echo "   See: docs/GOOGLE_SHEETS_SETUP.md"
    echo ""
    echo "3. Run initial update (or wait for 9 AM daily run):"
    echo "   systemctl --user start portfolio-update.service"
    echo ""
    echo "4. Monitor logs:"
    echo "   journalctl --user -u portfolio-update.service -f"
    echo ""
    echo "5. Check timer status:"
    echo "   systemctl --user list-timers portfolio-update.timer"
    echo ""
    echo "Your portfolio tracker is ready to use!"
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
    check_os
    check_systemd
    check_existing_database
    create_directories
    check_python
    check_dependencies

    # Confirm Python environment early (before doing any work)
    echo ""
    confirm_python_environment

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

    # Install systemd timers (optional)
    echo ""
    install_systemd_timers

    # Success
    echo ""
    print_next_steps

    exit 0
}

# Run main function
main
