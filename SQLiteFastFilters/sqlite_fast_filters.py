"""
SQLite database backend with SQL-accelerated filter overloads.
"""

from gramps.plugins.db.dbapi.sqlite import SQLite
from fastfilterslib.overload_rules import register_rules


class SQLiteFastFilters(SQLite):
    dialect = "sqlite"

    def _initialize(self, *args, **kwargs):
        super()._initialize(*args, **kwargs)
        register_rules(self)
