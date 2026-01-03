#!/usr/bin/env python3
"""
Bootstrap Accounts Script

Creates all your accounts with proper types and providers.
Run this once to initialize your account structure.

Usage:
    python scripts/bootstrap_accounts.py data/portfolio.db
"""

import sqlite3
import sys
from pathlib import Path


def add_provider(conn, name: str) -> int:
    """Add a provider and return its ID."""
    cursor = conn.execute("INSERT OR IGNORE INTO providers (name) VALUES (?)", (name,))
    conn.commit()

    cursor = conn.execute("SELECT id FROM providers WHERE name = ?", (name,))
    return cursor.fetchone()[0]


def add_account(conn, name: str, account_type: str, provider_name: str, notes: str = None):
    """Add an account with the specified type and provider."""
    # Get account type ID
    cursor = conn.execute("SELECT id FROM account_types WHERE name = ?", (account_type,))
    type_id = cursor.fetchone()

    if not type_id:
        print(f"  ✗ Unknown account type: {account_type}")
        return

    type_id = type_id[0]

    # Get or create provider
    provider_id = add_provider(conn, provider_name)

    # Insert account
    try:
        conn.execute(
            """
            INSERT INTO accounts (name, type, provider, notes, is_active)
            VALUES (?, ?, ?, ?, 1)
        """,
            (name, type_id, provider_id, notes),
        )
        conn.commit()
        print(f"  ✓ {name} ({account_type} @ {provider_name})")
    except sqlite3.IntegrityError:
        print(f"  ⚠ {name} already exists, skipping")


def bootstrap_accounts(db_path: str):
    """Bootstrap all accounts."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    print("Bootstrapping accounts...\n")

    # ========================================================================
    # BANK ACCOUNTS (Assets)
    # ========================================================================
    print("Bank Accounts:")
    add_account(conn, "OCBC Keith", "bank", "OCBC", "OCBC account - Keith")
    add_account(conn, "OCBC Evelyn", "bank", "OCBC", "OCBC account - Evelyn")
    add_account(conn, "CIMB Keith", "bank", "CIMB", "CIMB account - Keith")
    add_account(conn, "TMRW Evelyn", "bank", "UOB", "TMRW by UOB - Evelyn")
    add_account(conn, "BLUBCA Evelyn", "bank", "BCA", "BCA Blu - Evelyn")
    add_account(conn, "BCA Evelyn", "bank", "BCA", "BCA account - Evelyn")

    # ========================================================================
    # BROKERAGE ACCOUNTS (Assets)
    # ========================================================================
    print("\nBrokerage Accounts:")
    add_account(conn, "CGS-CIMB", "brokerage", "CGS-CIMB", "Stock brokerage")
    add_account(conn, "IBKR", "brokerage", "Interactive Brokers", "International stocks")
    add_account(conn, "Ajaib Evelyn", "brokerage", "Ajaib", "Stock brokerage - Evelyn")

    # ========================================================================
    # CRYPTO EXCHANGES (Assets)
    # ========================================================================
    print("\nCrypto Exchanges:")
    add_account(conn, "Binance", "exchange", "Binance", "Main crypto exchange")
    add_account(conn, "OKX", "exchange", "OKX", "Crypto exchange")
    add_account(conn, "Bitget Evelyn", "exchange", "Bitget", "Crypto exchange - Evelyn")
    add_account(conn, "Mobee Evelyn", "exchange", "Mobee", "Crypto exchange - Evelyn")
    add_account(conn, "Mobee Sus", "exchange", "Mobee", "Crypto exchange - Sus")

    # ========================================================================
    # CRYPTO WALLETS (Assets)
    # ========================================================================
    print("\nCrypto Wallets:")
    add_account(conn, "Cold Wallet Flex", "wallet", "Ledger", "Hardware wallet - Ledger Flex")
    add_account(conn, "Lighter Keith", "wallet", "Lighter", "Software wallet - Lighter")
    add_account(conn, "Mobee Keith", "wallet", "Mobee", "Mobee")

    # ========================================================================
    # CASH (Assets)
    # ========================================================================
    print("\nCash:")
    add_account(conn, "Cash in Hand", "cash", "Physical", "Physical cash holdings")

    # ========================================================================
    # LOANS/PAYABLES (Liabilities)
    # ========================================================================
    print("\nLiabilities:")
    add_account(conn, "Mama Egi Loan", "loan", "Personal", "Loan from Mama Egi")
    add_account(conn, "Gaji Sus", "payable", "Personal", "Gaji Sus payable")
    add_account(conn, "Papa Loan", "loan", "Personal", "Loan from Papa")

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "=" * 60)

    # Count by type
    cursor = conn.execute("""
        SELECT at.name, COUNT(*) as count
        FROM accounts a
        INNER JOIN account_types at ON a.type = at.id
        WHERE a.is_active = 1
        GROUP BY at.name
        ORDER BY at.name
    """)

    print("Account Summary:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    # Total
    cursor = conn.execute("SELECT COUNT(*) FROM accounts WHERE is_active = 1")
    total = cursor.fetchone()[0]
    print(f"\nTotal Active Accounts: {total}")

    conn.close()
    print("\n✓ Bootstrap complete!")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/bootstrap_accounts.py data/portfolio.db")
        sys.exit(1)

    db_path = sys.argv[1]

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        print("Run: python scripts/init_db.py {db_path}")
        sys.exit(1)

    bootstrap_accounts(db_path)


if __name__ == "__main__":
    main()
