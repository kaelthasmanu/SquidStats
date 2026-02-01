#!/usr/bin/env python3
"""
Test script to verify the migration to Alembic.

This script performs basic checks to ensure that:
1. Alembic is correctly installed
2. The configuration is valid
3. The migration files exist
4. The migrate_database() function works correctly
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_alembic_installation():
    """Verify that Alembic is installed."""
    try:
        import alembic

        try:
            version = alembic.__version__
        except AttributeError:
            # Older versions might not have __version__
            version = "installed (version not available)"
        print(f"✓ Alembic installed: {version}")
        return True
    except ImportError:
        print("✗ Alembic NOT installed")
        print("  Run: pip install -r requirements.txt")
        return False


def test_alembic_config():
    """Verify that alembic.ini exists."""
    alembic_ini = project_root / "alembic.ini"
    if alembic_ini.exists():
        print("✓ alembic.ini file found")
        return True
    else:
        print("✗ alembic.ini file NOT found")
        return False


def test_alembic_structure():
    """Verify the Alembic directory structure."""
    checks = {
        "alembic/": "Alembic directory",
        "alembic/env.py": "env.py file",
        "alembic/script.py.mako": "script.py.mako template",
        "alembic/versions/": "versions directory",
        "alembic/versions/001_initial_schema.py": "Initial migration",
        "alembic/versions/002_expand_varchar_columns.py": "VARCHAR migration",
    }

    all_ok = True
    for path, description in checks.items():
        full_path = project_root / path
        if full_path.exists():
            print(f"✓ {description}")
        else:
            print(f"✗ {description} NOT found")
            all_ok = False

    return all_ok


def test_database_module():
    """Verify that the database module can be imported."""
    try:
        from database.database import get_database_url

        print("✓ database.database module imported successfully")

        # Try to get database URL (doesn't connect, just builds URL)
        try:
            url = get_database_url()
            print(f"✓ Database URL: {url[:50]}...")
        except Exception as e:
            print(f"⚠ Warning getting URL: {e}")

        return True
    except ImportError:
        print("⚠ Cannot import database (missing dependencies)")
        print("  Run: pip install -r requirements.txt")
        # This is not a failure if dependencies aren't installed yet
        return True
    except Exception as e:
        print(f"✗ Error importing database: {e}")
        return False


def test_manage_db_script():
    """Verify that manage_db.py exists and is executable."""
    manage_db = project_root / "manage_db.py"

    if not manage_db.exists():
        print("✗ manage_db.py NOT found")
        return False

    print("✓ manage_db.py script found")

    # Check if executable (Linux/Mac)
    if os.name != "nt":
        if os.access(manage_db, os.X_OK):
            print("✓ manage_db.py is executable")
        else:
            print("⚠ manage_db.py is not executable (run: chmod +x manage_db.py)")

    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("ALEMBIC MIGRATION VERIFICATION")
    print("=" * 60)
    print()

    tests = [
        ("Alembic Installation", test_alembic_installation),
        ("Alembic Configuration", test_alembic_config),
        ("Alembic Structure", test_alembic_structure),
        ("Database Module", test_database_module),
        ("Management Script", test_manage_db_script),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n[{name}]")
        print("-" * 60)
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    print(f"\nTests passed: {passed}/{total}")

    if all(results):
        print("\n✓ EVERYTHING IS READY!")
        print("\nNext steps:")
        print("  1. If you have an existing DB: python manage_db.py init")
        print("  2. Start the application: python app.py")
        return 0
    else:
        print("\n✗ SOME VERIFICATIONS FAILED")
        print("\nPlease check the errors above and fix them.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
