"""
FastFiltersLib — shared library for SQLiteFastFilters and PostgreSQLFastFilters.

Importing this module at load_on_reg time caches the fastfilterslib package
submodules in sys.modules so that the database backend addons can import
them with dotted names (e.g. `from fastfilterslib.overload_rules import
register_rules`) regardless of which directory is currently on sys.path.
"""

import fastfilterslib.sql_compat  # noqa: F401
import fastfilterslib.overload_rules  # noqa: F401
