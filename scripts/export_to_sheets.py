#!/usr/bin/env python3
"""
Google Sheets Export Script

Exports analytics views from SQLite database to Google Sheets for dashboard
visualization. Runs in overwrite mode - clears and rewrites tabs on each run.

Usage:
    # Export using default database
    python scripts/export_to_sheets.py

    # Export with custom database
    python scripts/export_to_sheets.py /path/to/portfolio.db

    # Override sheet ID
    python scripts/export_to_sheets.py --sheet-id=1ABC...XYZ

Environment Variables:
    GOOGLE_CREDENTIALS_PATH - Path to service account JSON
    EXPORT_SHEET_ID - Google Sheet ID (preferred)
    GOOGLE_SHEET_ID - Fallback sheet ID

Exported Tabs:
    - Summary: Assets, Liabilities, Net Worth
    - By Asset Class: Breakdown by crypto/stocks/fiat
    - By Currency: Holdings per currency
    - History: Daily net worth time series

Example Cron (every 6 hours, 5min after ingestion):
    5 */6 * * * cd /path && python scripts/export_to_sheets.py >> logs/export.log 2>&1
"""

import argparse
import fcntl
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Column type hints for formatting
VIEW_COLUMN_TYPES = {
    "net_worth_summary": ["text", "numeric", "numeric"],
    "net_worth_by_asset_class": ["text", "numeric", "numeric", "numeric"],
    "net_worth_by_currency": ["text", "text", "numeric", "numeric", "numeric"],
    "net_worth_history": ["date", "numeric", "numeric"],
}


def setup_logging(log_dir: Path) -> logging.Logger:
    """Setup logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)

    # Simple formatter without logger name to avoid duplication
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear existing handlers to prevent duplication
    logger.handlers.clear()

    # File handler with monthly rotation
    log_file = log_dir / f"export_{datetime.now().strftime('%Y%m')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class LockFile:
    """Context manager for file-based locking."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock_file = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self.lock_path, "w")
        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_file.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
            self.lock_file.flush()
            return self
        except IOError:
            self.lock_file.close()
            raise RuntimeError(
                f"Another instance is already running (lock file: {self.lock_path})"
            )

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            try:
                self.lock_path.unlink()
            except:
                pass


def validate_database(db_path: Path) -> bool:
    """
    Validate database exists and has required views.

    Returns:
        True if valid, False otherwise
    """
    if not db_path.exists():
        logging.error(f"Database not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='view'
            AND name IN (
                'net_worth_summary',
                'net_worth_by_asset_class',
                'net_worth_by_currency',
                'net_worth_history'
            )
        """
        )
        views = {row[0] for row in cursor.fetchall()}
        conn.close()

        required_views = {
            "net_worth_summary",
            "net_worth_by_asset_class",
            "net_worth_by_currency",
            "net_worth_history",
        }

        if not required_views.issubset(views):
            missing = required_views - views
            logging.error(f"Missing required views: {missing}")
            return False

        return True

    except sqlite3.Error as e:
        logging.error(f"Database validation error: {e}")
        return False


def validate_data_exists(db_path: str) -> bool:
    """
    Check if database has balance data worth exporting.

    Returns:
        True if data exists, False if empty
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM balances")
        count = cursor.fetchone()[0]
        conn.close()

        if count == 0:
            logging.warning("Database has no balance data - nothing to export")
            return False

        logging.info(f"Database contains {count} balance records")
        return True

    except sqlite3.Error as e:
        logging.error(f"Failed to check data: {e}")
        return False


def query_view_data(db_path: str, view_name: str) -> Tuple[List[str], List[tuple]]:
    """
    Query a database view and return headers and data.

    Args:
        db_path: Path to SQLite database
        view_name: Name of view to query

    Returns:
        Tuple of (column_names, rows)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(f"SELECT * FROM {view_name}")

    # Extract column names from cursor description
    column_names = [description[0] for description in cursor.description]

    # Fetch all rows
    rows = cursor.fetchall()

    conn.close()

    logging.info(f"✓ Queried {view_name}: {len(rows)} rows, {len(column_names)} columns")
    return column_names, rows


def format_numeric_value(value, decimals: int = 2) -> str:
    """
    Format numeric value for spreadsheet display.

    Args:
        value: Numeric value (float, int, or None)
        decimals: Number of decimal places

    Returns:
        Formatted string or empty string for None
    """
    if value is None:
        return ""

    try:
        return f"{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def format_row_for_sheets(row: tuple, column_types: List[str]) -> List[str]:
    """
    Format a database row for Google Sheets.

    Args:
        row: Database row tuple
        column_types: List indicating data type per column
                     ('text', 'numeric', 'date')

    Returns:
        List of formatted string values
    """
    formatted = []

    for value, col_type in zip(row, column_types):
        if col_type == "numeric":
            formatted.append(format_numeric_value(value))
        elif col_type == "date":
            formatted.append(str(value) if value else "")
        else:  # text
            formatted.append(str(value) if value else "")

    return formatted


def create_sheets_service(credentials_path: str):
    """
    Create authenticated Google Sheets API service.

    Args:
        credentials_path: Path to service account JSON file

    Returns:
        Google Sheets API service object
    """
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(f"Credentials not found: {credentials_path}")

    # CRITICAL: Use 'spreadsheets' scope (not readonly)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = ServiceAccountCredentials.from_service_account_file(
        credentials_path, scopes=scopes
    )

    service = build("sheets", "v4", credentials=creds)

    logging.info("✓ Authenticated with Google Sheets API")
    return service


def get_or_create_sheet_tab(service, spreadsheet_id: str, tab_name: str) -> int:
    """
    Get sheet ID for tab, creating it if it doesn't exist.

    Args:
        service: Google Sheets API service
        spreadsheet_id: Target spreadsheet ID
        tab_name: Name of tab/sheet

    Returns:
        Sheet ID (integer)
    """
    try:
        # Get current sheets
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

        # Find matching sheet by title
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == tab_name:
                sheet_id = sheet["properties"]["sheetId"]
                logging.info(f"✓ Found existing tab: '{tab_name}' (ID: {sheet_id})")
                return sheet_id

        # Sheet doesn't exist - create it
        logging.info(f"Creating new tab: '{tab_name}'")
        request_body = {
            "requests": [{"addSheet": {"properties": {"title": tab_name}}}]
        }

        response = (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=request_body)
            .execute()
        )

        sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
        logging.info(f"✓ Created tab: '{tab_name}' (ID: {sheet_id})")
        return sheet_id

    except HttpError as e:
        logging.error(f"✗ Failed to get/create tab '{tab_name}': {e}")
        raise


def clear_sheet_data(service, spreadsheet_id: str, tab_name: str):
    """
    Clear existing data from a sheet tab.

    Uses clear() instead of batchUpdate to preserve:
    - Chart objects
    - Conditional formatting
    - Data validation rules

    Args:
        service: Google Sheets API service
        spreadsheet_id: Target spreadsheet ID
        tab_name: Name of tab to clear
    """
    try:
        # Clear all data (A1 notation with no end = entire sheet)
        range_name = f"{tab_name}!A1:ZZ"

        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=range_name, body={}
        ).execute()

        logging.info(f"✓ Cleared data in tab: '{tab_name}'")

    except HttpError as e:
        logging.error(f"✗ Failed to clear tab '{tab_name}': {e}")
        raise


def write_sheet_data(
    service,
    spreadsheet_id: str,
    tab_name: str,
    headers: List[str],
    rows: List[List[str]],
    timestamp: datetime,
):
    """
    Write data to Google Sheet with headers and timestamp.

    Layout:
        Row 1: Headers
        Row 2-N: Data rows
        Row N+2: Blank
        Row N+3: Timestamp footer

    Args:
        service: Google Sheets API service
        spreadsheet_id: Target spreadsheet ID
        tab_name: Name of tab
        headers: Column headers
        rows: Data rows (already formatted)
        timestamp: Export timestamp
    """
    try:
        # Build values array: headers + data + blank + timestamp
        values = [headers] + rows + [[]]  + [[f"Exported: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"]]

        # Write all at once using update
        range_name = f"{tab_name}!A1"

        body = {"values": values}

        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",  # Don't parse formulas
                body=body,
            )
            .execute()
        )

        updated_cells = result.get("updatedCells", 0)
        logging.info(
            f"✓ Wrote {len(rows)} rows to '{tab_name}' ({updated_cells} cells updated)"
        )

    except HttpError as e:
        logging.error(f"✗ Failed to write data to '{tab_name}': {e}")
        raise


def format_header_row(service, spreadsheet_id: str, sheet_id: int):
    """
    Apply bold formatting to header row (row 1).

    Optional enhancement for better readability.

    Args:
        service: Google Sheets API service
        spreadsheet_id: Target spreadsheet ID
        sheet_id: Numeric sheet ID (not tab name)
    """
    try:
        request_body = {
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                        },
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                }
            ]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=request_body
        ).execute()

        logging.debug(f"✓ Applied header formatting to sheet ID {sheet_id}")

    except HttpError as e:
        # Non-critical - don't fail export if formatting fails
        logging.warning(f"Could not format headers for sheet {sheet_id}: {e}")


def export_view_to_sheet(
    service,
    spreadsheet_id: str,
    db_path: str,
    view_name: str,
    tab_name: str,
    column_types: List[str],
    timestamp: datetime,
) -> bool:
    """
    Export a single database view to a Google Sheets tab.

    Complete flow:
        1. Query database view
        2. Ensure tab exists
        3. Clear existing data
        4. Format data
        5. Write to sheet
        6. Apply formatting

    Args:
        service: Google Sheets API service
        spreadsheet_id: Target spreadsheet ID
        db_path: Path to SQLite database
        view_name: Database view name
        tab_name: Google Sheets tab name
        column_types: List of column type hints
        timestamp: Export timestamp

    Returns:
        True if successful, False otherwise
    """
    try:
        logging.info("=" * 70)
        logging.info(f"Exporting: {view_name} → {tab_name}")
        logging.info("=" * 70)

        # 1. Query database
        headers, raw_rows = query_view_data(db_path, view_name)

        if not raw_rows:
            logging.warning(f"View '{view_name}' has no data - writing headers only")

        # 2. Ensure tab exists
        sheet_id = get_or_create_sheet_tab(service, spreadsheet_id, tab_name)

        # 3. Clear existing data
        clear_sheet_data(service, spreadsheet_id, tab_name)

        # 4. Format data
        formatted_rows = [format_row_for_sheets(row, column_types) for row in raw_rows]

        # 5. Write to sheet
        write_sheet_data(
            service, spreadsheet_id, tab_name, headers, formatted_rows, timestamp
        )

        # 6. Format header (optional)
        format_header_row(service, spreadsheet_id, sheet_id)

        logging.info(f"✓ Successfully exported {view_name}")
        return True

    except Exception as e:
        logging.error(f"✗ Failed to export {view_name}: {e}")
        return False


def export_all_views(
    service, spreadsheet_id: str, db_path: str, timestamp: datetime
) -> Dict[str, bool]:
    """
    Export all analytics views to Google Sheets.

    Args:
        service: Google Sheets API service
        spreadsheet_id: Target spreadsheet ID
        db_path: Path to SQLite database
        timestamp: Export timestamp

    Returns:
        Dict mapping tab names to success status
    """
    # Define view configurations
    view_configs = [
        {
            "view_name": "net_worth_summary",
            "tab_name": "Summary",
            "column_types": ["text", "numeric", "numeric"],
        },
        {
            "view_name": "net_worth_by_asset_class",
            "tab_name": "By Asset Class",
            "column_types": ["text", "numeric", "numeric", "numeric"],
        },
        {
            "view_name": "net_worth_by_currency",
            "tab_name": "By Currency",
            "column_types": ["text", "text", "numeric", "numeric", "numeric"],
        },
        {
            "view_name": "net_worth_history",
            "tab_name": "History",
            "column_types": ["date", "numeric", "numeric"],
        },
    ]

    results = {}

    for config in view_configs:
        success = export_view_to_sheet(
            service=service,
            spreadsheet_id=spreadsheet_id,
            db_path=db_path,
            view_name=config["view_name"],
            tab_name=config["tab_name"],
            column_types=config["column_types"],
            timestamp=timestamp,
        )
        results[config["tab_name"]] = success

    return results


def main():
    """Main entry point."""
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Export analytics views from SQLite to Google Sheets"
    )
    parser.add_argument(
        "database",
        nargs="?",
        default="data/portfolio.db",
        help="Path to SQLite database (default: data/portfolio.db)",
    )
    parser.add_argument("--sheet-id", help="Override EXPORT_SHEET_ID from environment")

    args = parser.parse_args()
    db_path = Path(args.database)

    # Setup paths
    project_root = Path(__file__).parent.parent
    log_dir = project_root / "logs"
    lock_file = project_root / "data" / ".export.lock"

    # Setup logging
    logger = setup_logging(log_dir)

    logger.info("=" * 70)
    logger.info("Google Sheets Export - Starting")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")

    try:
        # Load environment
        load_dotenv()

        # Get configuration
        credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        sheet_id = (
            args.sheet_id
            or os.getenv("EXPORT_SHEET_ID")
            or os.getenv("GOOGLE_SHEET_ID")
        )

        if not credentials_path:
            logger.error("GOOGLE_CREDENTIALS_PATH not set in environment")
            sys.exit(1)

        if not sheet_id:
            logger.error("EXPORT_SHEET_ID or GOOGLE_SHEET_ID not set in environment")
            sys.exit(1)

        logger.info(f"Credentials: {credentials_path}")
        logger.info(f"Sheet ID: {sheet_id[:20]}...")

        # Acquire lock
        with LockFile(lock_file):
            logger.info("✓ Lock acquired")

            # Validate database
            if not validate_database(db_path):
                logger.error("Database validation failed")
                sys.exit(1)

            # Check for data
            if not validate_data_exists(str(db_path)):
                logger.error("No data to export")
                sys.exit(1)

            # Create Google Sheets service
            service = create_sheets_service(credentials_path)

            # Export all views
            timestamp = datetime.now()
            results = export_all_views(service, sheet_id, str(db_path), timestamp)

            # Summary
            successful = sum(1 for success in results.values() if success)
            total = len(results)

            logger.info("=" * 70)
            logger.info("EXPORT SUMMARY")
            logger.info("=" * 70)

            for tab_name, success in results.items():
                status = "✓" if success else "✗"
                logger.info(f"{status} {tab_name}")

            logger.info("=" * 70)

            if successful == total:
                logger.info(f"✓ All {total} views exported successfully")
                sys.exit(0)
            else:
                logger.error(f"✗ Only {successful}/{total} views exported")
                sys.exit(1)

    except RuntimeError as e:
        # Lock file error
        logger.warning(str(e))
        sys.exit(2)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        logger.error("=" * 70)
        logger.error("Export failed with error")
        logger.error("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
