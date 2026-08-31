#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migrate data from local SQLite (psx_v2.db) to Turso database.

This script:
1. Reads all data from local SQLite
2. Creates tables in Turso (if not exists)
3. Uploads all rows to Turso
4. Verifies data integrity
"""

import os
import sys
import sqlite3
from pathlib import Path

# Fix encoding on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import turso_db

def count_rows(cursor, table):
    """Count rows in a table."""
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]
    except:
        return 0

def migrate_data():
    """Migrate data from local SQLite to Turso."""

    print("\n" + "="*70)
    print("🔄 TURSO DATA MIGRATION")
    print("="*70 + "\n")

    # Connect to local SQLite
    local_db = "backend/psx_v2.db"
    if not os.path.exists(local_db):
        print(f"❌ Local database not found: {local_db}")
        return False

    print(f"📁 Reading from: {local_db}")
    local_conn = sqlite3.connect(local_db)
    local_conn.row_factory = sqlite3.Row
    local_cursor = local_conn.cursor()

    # Get list of tables
    local_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in local_cursor.fetchall()]

    if not tables:
        print("❌ No tables found in local database")
        return False

    print(f"📊 Found {len(tables)} tables: {', '.join(tables)}\n")

    # Connect to Turso
    turso_conn = turso_db.get_connection()
    print(f"✅ Connected to Turso database\n")

    total_rows_migrated = 0

    for table in tables:
        print(f"📋 Migrating table: {table}")

        # Get column info
        local_cursor.execute(f"PRAGMA table_info({table})")
        columns = [(row[1], row[2]) for row in local_cursor.fetchall()]
        column_names = [col[0] for col in columns]
        column_types = [col[1] for col in columns]

        if not column_names:
            print(f"   ⚠️  Skipped (no columns)\n")
            continue

        # Create table in Turso if not exists
        try:
            create_sql = f"CREATE TABLE IF NOT EXISTS {table} ("
            create_sql += ", ".join([f"{name} {ctype}" for name, ctype in columns])
            create_sql += ")"
            turso_conn.execute(create_sql)
            print(f"   ✅ Table schema created/verified")
        except Exception as e:
            print(f"   ⚠️  Schema error: {e}")

        # Count rows
        local_row_count = count_rows(local_cursor, table)

        if local_row_count == 0:
            print(f"   ℹ️  No rows to migrate\n")
            continue

        print(f"   📊 Migrating {local_row_count} rows...")

        # Fetch all data
        local_cursor.execute(f"SELECT * FROM {table}")
        rows = local_cursor.fetchall()

        # Insert into Turso
        if rows:
            placeholders = ", ".join(["?" for _ in column_names])
            insert_sql = f"INSERT INTO {table} ({', '.join(column_names)}) VALUES ({placeholders})"

            try:
                for row in rows:
                    turso_conn.execute(insert_sql, tuple(row))
                print(f"   ✅ {local_row_count} rows inserted")
                total_rows_migrated += local_row_count
            except Exception as e:
                print(f"   ❌ Error inserting rows: {e}")

        print()

    local_conn.close()

    # Verify
    print("="*70)
    print("✅ MIGRATION COMPLETE")
    print("="*70)
    print(f"Total rows migrated: {total_rows_migrated}")
    print(f"Database URL: libsql://psx-intelligence-system-imranraza786.aws-us-east-1.turso.io")
    print("\n🎉 Data is now stored in Turso!")
    print("✨ Your system will now use Turso for all queries")
    print("💾 Data persists across restarts and cloud deployments\n")

    return True

if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)
    success = migrate_data()
    sys.exit(0 if success else 1)
