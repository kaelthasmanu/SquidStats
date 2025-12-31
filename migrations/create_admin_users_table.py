#!/usr/bin/env python3
"""
Migration script to create the admin_users table and default admin user.
This creates the authentication system for admin users.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from sqlalchemy import inspect

from database.database import AdminUser, get_engine, get_session


def hash_password(password: str) -> tuple[str, str]:
    """Hash a password with bcrypt and return (hash, salt)."""
    # Generate salt and hash
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode("utf-8"), salt)
    return password_hash.decode("utf-8"), salt.decode("utf-8")


def main():
    """Create admin_users table and default admin user."""
    print("=" * 60)
    print("ADMIN USERS TABLE MIGRATION")
    print("=" * 60)

    engine = get_engine()
    session = get_session()

    try:
        inspector = inspect(engine)

        # Check if table already exists
        if "admin_users" in inspector.get_table_names():
            print("✓ Admin users table already exists")

            # Check if default admin user exists
            existing_admin = (
                session.query(AdminUser).filter_by(username="admin").first()
            )
            if existing_admin:
                print("✓ Default admin user already exists")
                return
            else:
                print("Creating default admin user...")
        else:
            print("Creating admin_users table...")
            # Create the table
            AdminUser.__table__.create(engine, checkfirst=True)
            print("✓ Admin users table created successfully")

        # Create default admin user with FIRST_PASSWORD
        first_password = os.getenv("FIRST_PASSWORD", "").strip()

        if not first_password:
            print("✗ FIRST_PASSWORD not set in .env file")
            print(
                "  Please set FIRST_PASSWORD in your .env file and run migration again."
            )
            print('  Example: FIRST_PASSWORD="your_secure_password"')
            return

        # Hash the password
        password_hash, salt = hash_password(first_password)

        admin_user = AdminUser(
            username="admin",
            password_hash=password_hash,
            salt=salt,
            role="admin",
            is_active=1,
        )

        session.add(admin_user)
        session.commit()

        print("✓ Default admin user created successfully")
        print("  Username: admin")
        print("  Password: Set from FIRST_PASSWORD")
        print("  Use change_password.py to update the password after first login")
        print("\nTable structure:")
        print("  - id: Primary key (auto-increment)")
        print("  - username: Unique username (indexed)")
        print("  - password_hash: bcrypt hashed password")
        print("  - salt: Salt used for password hashing")
        print("  - role: User role (default: admin)")
        print("  - is_active: Account status (1 = active, 0 = inactive)")
        print("  - last_login: Last login timestamp")
        print("  - created_at: Account creation timestamp")
        print("  - updated_at: Last update timestamp")

    except Exception as e:
        session.rollback()
        print(f"✗ Error during migration: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
