import os
import sys
from pathlib import Path

# add the parent directory to the system path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import unittest

from sqlalchemy import create_engine, inspect

import database.database as db_module
from database.database import create_dynamic_tables, get_dynamic_table_names


class TestTableCreation(unittest.TestCase):
    def setUp(self):
        # Reset global singletons so each test gets a clean in-memory DB
        db_module._engine = None
        db_module._Session = None
        db_module.dynamic_model_cache.clear()

        # Set environment variables for in-memory SQLite
        os.environ["DATABASE_TYPE"] = "SQLITE"
        os.environ["DATABASE_STRING_CONNECTION"] = ":memory:"

        self.engine = create_engine("sqlite:///:memory:", echo=False, future=True)
        db_module._engine = self.engine

    def tearDown(self):
        self.engine.dispose()
        # Clean up singletons after each test
        db_module._engine = None
        db_module._Session = None
        db_module.dynamic_model_cache.clear()

    def test_table_creation(self):
        # Verify tables do not exist in a fresh engine
        inspector = inspect(self.engine)
        current_tables = inspector.get_table_names()
        table_names = get_dynamic_table_names()
        for table in table_names:
            self.assertNotIn(table, current_tables)

        # Trigger table creation explicitly
        create_dynamic_tables(self.engine)

        # Refresh the inspector to get the latest table names
        inspector = inspect(self.engine)
        current_tables = inspector.get_table_names()
        for table in table_names:
            self.assertIn(table, current_tables)

        # New quota tables must also exist
        for quota_table in [
            "quota_users",
            "quota_groups",
            "quota_rules",
            "quota_events",
        ]:
            self.assertIn(quota_table, current_tables)


if __name__ == "__main__":
    unittest.main()
