#!/usr/bin/env python3
"""
Personal Finance Tracker - Database Initialization Script

This script creates the SQLite database with the complete schema including:
- All lookup tables (currency_types, account_types, providers)
- Master data tables (currencies, accounts)
- Transactional tables (fx_rates, balances)
- Indexes for optimal query performance
- Views for reporting

Usage:
    python init_db.py [database_path]

    If no database_path is provided, defaults to 'portfolio.db'
"""

import sqlite3
import sys
from pathlib import Path


def init_database(db_path: str = "portfolio.db") -> None:
    """
    Initialize the database with the complete schema.

    Args:
        db_path: Path to the SQLite database file
    """
    # Read schema file
    schema_path = Path(__file__).parent.parent / "sql" / "schema.sql"

    if not schema_path.exists():
        print(f"Error: schema.sql not found at {schema_path}")
        sys.exit(1)

    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    # Create/connect to database
    print(f"Initializing database at: {db_path}")
    conn = sqlite3.connect(db_path)

    try:
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")

        # Execute schema
        conn.executescript(schema_sql)
        conn.commit()

        # Verify tables were created
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        print("\n✓ Database initialized successfully!")
        print(f"\nCreated {len(tables)} tables:")
        for table in tables:
            print(f"  • {table}")

        # Verify views were created
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        )
        views = [row[0] for row in cursor.fetchall()]

        print(f"\nCreated {len(views)} views:")
        for view in views:
            print(f"  • {view}")

        # Show seed data
        cursor = conn.execute("SELECT name FROM currency_types")
        currency_types = [row[0] for row in cursor.fetchall()]
        print(f"\nSeeded currency_types: {', '.join(currency_types)}")

        cursor = conn.execute("SELECT name FROM account_types")
        account_types = [row[0] for row in cursor.fetchall()]
        print(f"Seeded account_types: {', '.join(account_types)}")

        print("\n✓ Database is ready for use!")

    except sqlite3.Error as e:
        print(f"\n✗ Error initializing database: {e}")
        sys.exit(1)
    finally:
        conn.close()


def main():
    """Main entry point."""
    db_path = sys.argv[1] if len(sys.argv) > 1 else "portfolio.db"

    # Warn if database already exists
    if Path(db_path).exists():
        response = input(
            f"\n⚠️  Database '{db_path}' already exists.\n"
            "This will run schema migrations but won't delete existing data.\n"
            "Continue? [y/N]: "
        )
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    init_database(db_path)


if __name__ == "__main__":
    main()
