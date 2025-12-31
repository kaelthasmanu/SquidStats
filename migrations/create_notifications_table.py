#!/usr/bin/env python3
"""
Migration script to create the notifications table MANUALLY
This is OPTIONAL - the table is automatically created when the app starts.
Only run this if you want to create the table before starting the app.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect

from database.database import Notification, get_engine


def main():
    """Create notifications table if it doesn't exist"""
    print("=" * 60)
    print("NOTIFICATIONS TABLE MIGRATION (OPTIONAL)")
    print("=" * 60)
    print("\nNOTE: This table is automatically created when the app starts.")
    print("You only need to run this if you want to create it manually.\n")

    engine = get_engine()
    inspector = inspect(engine)

    # Check if table already exists
    if "notifications" in inspector.get_table_names():
        print("✓ Notifications table already exists")
        print("\nTable structure:")
        columns = inspector.get_columns("notifications")
        for col in columns:
            nullable = "NULL" if col["nullable"] else "NOT NULL"
            print(f"  - {col['name']}: {col['type']} {nullable}")
        return

    print("Creating notifications table...")

    # Create only the Notification table
    Notification.__table__.create(engine, checkfirst=True)

    print("✓ Notifications table created successfully")
    print("\nTable structure:")
    print("  - id: Primary key (auto-increment)")
    print("  - type: Notification type (info, warning, error, success)")
    print("  - message: Notification message text")
    print("  - message_hash: SHA256 hash for deduplication")
    print("  - icon: FontAwesome icon class")
    print("  - source: Source of notification (squid, system, security, users, git)")
    print("  - read: Read status (0=unread, 1=read)")
    print("  - created_at: Creation timestamp")
    print("  - updated_at: Last update timestamp")
    print("  - expires_at: Optional expiration date")
    print("  - count: Number of times notification was triggered")
    print("\nIndexes created on: message_hash, source, created_at")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"✗ Error creating notifications table: {e}")
        sys.exit(1)
