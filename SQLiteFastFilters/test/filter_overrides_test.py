"""
SQLite-specific filter override integration tests.

Test logic lives in FastFiltersLib/test/filter_overrides_base.py; each class
here only supplies _open_db() to provide a SQLite-backed database.
"""

import os
import unittest

from gramps.gen.const import TEST_DIR
from gramps.gen.db.utils import import_as_dict, make_database
from gramps.gen.user import User

from filter_overrides_base import (
    ExampleDatabaseTestsMixin,
    PrivateFilterTestsMixin,
    SmallDatabaseTestsMixin,
    SQLPathTestsMixin,
)

EXAMPLE = os.path.join(TEST_DIR, "example.gramps")


class TestWithSmallDatabase(SmallDatabaseTestsMixin, unittest.TestCase):
    @classmethod
    def _open_db(cls):
        db = make_database("sqlite")
        db.load(":memory:")
        return db


class TestAgainstExampleDatabase(ExampleDatabaseTestsMixin, unittest.TestCase):
    @classmethod
    def _open_db(cls):
        return import_as_dict(EXAMPLE, User())


class TestSQLPathIsUsed(SQLPathTestsMixin, unittest.TestCase):
    @classmethod
    def _open_db(cls):
        db = make_database("sqlite")
        db.load(":memory:")
        return db


class TestPrivateFilters(PrivateFilterTestsMixin, unittest.TestCase):
    @classmethod
    def _open_db(cls):
        db = make_database("sqlite")
        db.load(":memory:")
        return db
