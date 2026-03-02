import os
import sys
from pathlib import Path

# add the parent directory to the system path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import unittest

from sqlalchemy import MetaData, inspect

from database.database import get_dynamic_table_names, get_engine
from parsers.log import DatabaseManager


class TestTableCreation(unittest.TestCase):
    def setUp(self):
        # Set environment variables for in-memory SQLite
        os.environ["DATABASE_TYPE"] = "SQLITE"
        os.environ["DATABASE_STRING_CONNECTION"] = ":memory:"
        self.engine = get_engine()
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = DatabaseManager(engine=self.engine).session

    def tearDown(self):
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def test_table_creation(self):
        # Drop ALL tables (static + dynamic) to simulate a fresh database
        meta = MetaData()
        meta.reflect(bind=self.engine)
        meta.drop_all(bind=self.engine)

        # Verify tables do not exist initially
        inspector = inspect(self.engine)
        current_tables = inspector.get_table_names()
        table_names = get_dynamic_table_names()
        for table in table_names:
            self.assertNotIn(table, current_tables)

        # Trigger table creation logic usando el mismo engine
        with DatabaseManager(engine=self.engine):
            pass

        # Refresh the inspector to get the latest table names
        inspector = inspect(self.engine)
        current_tables = inspector.get_table_names()
        for table in table_names:
            self.assertIn(table, current_tables)


if __name__ == "__main__":
    unittest.main()
