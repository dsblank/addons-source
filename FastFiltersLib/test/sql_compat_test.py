"""
Unit tests for sql_compat.SQLCompat.

These tests cover both dialect variants without touching a database.
Where possible, the generated SQL is also executed against an in-process
sqlite3 connection to ensure the SQLite fragments are syntactically valid.
"""

import sqlite3
import unittest

from fastfilterslib.sql_compat import SQLCompat


def _sqlite_exec(sql, params=()):
    """Execute *sql* against a fresh in-memory SQLite DB and return all rows."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE person "
        "(handle TEXT PRIMARY KEY, gender INTEGER, json_data TEXT)"
    )
    con.execute(
        "INSERT INTO person VALUES ('h1', 1, "
        "'{\"family_list\":[],\"parent_family_list\":[],\"alternate_names\":[]}')"
    )
    con.execute(
        "INSERT INTO person VALUES ('h2', 0, "
        "'{\"family_list\":[\"fam1\"],\"parent_family_list\":[],\"alternate_names\":[\"alt\"]}')"
    )
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows


class TestSQLCompatDialectValidation(unittest.TestCase):
    def test_valid_sqlite(self):
        SQLCompat("sqlite")

    def test_valid_postgresql(self):
        SQLCompat("postgresql")

    def test_invalid_dialect_raises(self):
        with self.assertRaises(ValueError):
            SQLCompat("mysql")

    def test_for_db_with_dialect_attr(self):
        class _FakeDB:
            dialect = "postgresql"

        compat = SQLCompat.for_db(_FakeDB())
        self.assertEqual(compat.dialect, "postgresql")

    def test_for_db_defaults_to_sqlite(self):
        class _FakeDB:
            pass

        compat = SQLCompat.for_db(_FakeDB())
        self.assertEqual(compat.dialect, "sqlite")


class TestPlaceholder(unittest.TestCase):
    def test_sqlite(self):
        self.assertEqual(SQLCompat("sqlite").placeholder(), "?")

    def test_postgresql(self):
        self.assertEqual(SQLCompat("postgresql").placeholder(), "%s")


class TestRegexp(unittest.TestCase):
    def test_sqlite_form(self):
        expr = SQLCompat("sqlite").regexp("given_name", "?")
        self.assertEqual(expr, "regexp(?, given_name)")

    def test_postgresql_form(self):
        expr = SQLCompat("postgresql").regexp("given_name", "%s")
        self.assertEqual(expr, "given_name ~ %s")

    def test_sqlite_with_literal_pattern(self):
        expr = SQLCompat("sqlite").regexp("surname", "'Smith'")
        self.assertEqual(expr, "regexp('Smith', surname)")

    def test_postgresql_with_literal_pattern(self):
        expr = SQLCompat("postgresql").regexp("surname", "'Smith'")
        self.assertEqual(expr, "surname ~ 'Smith'")


class TestIlike(unittest.TestCase):
    def test_sqlite_form(self):
        expr = SQLCompat("sqlite").ilike("surname", "?")
        self.assertEqual(expr, "lower(surname) LIKE lower(?)")

    def test_postgresql_form(self):
        expr = SQLCompat("postgresql").ilike("surname", "%s")
        self.assertEqual(expr, "surname ILIKE %s")


class TestJsonExtract(unittest.TestCase):
    def test_sqlite_flat(self):
        expr = SQLCompat("sqlite").json_extract("json_data", "gramps_id")
        self.assertEqual(expr, "json_extract(json_data, '$.gramps_id')")

    def test_sqlite_nested(self):
        expr = SQLCompat("sqlite").json_extract(
            "json_data", "primary_name.first_name"
        )
        self.assertEqual(
            expr, "json_extract(json_data, '$.primary_name.first_name')"
        )

    def test_postgresql_flat(self):
        expr = SQLCompat("postgresql").json_extract("json_data", "gramps_id")
        self.assertEqual(expr, "(json_data::json)->>'gramps_id'")

    def test_postgresql_nested(self):
        expr = SQLCompat("postgresql").json_extract(
            "json_data", "primary_name.first_name"
        )
        self.assertEqual(
            expr, "((json_data::json)->'primary_name')->>'first_name'"
        )

    def test_sqlite_sql_is_executable(self):
        expr = SQLCompat("sqlite").json_extract("json_data", "family_list")
        rows = _sqlite_exec(f"SELECT handle FROM person WHERE {expr} IS NOT NULL")
        self.assertEqual(len(rows), 2)


class TestJsonArrayLength(unittest.TestCase):
    def test_sqlite_flat(self):
        expr = SQLCompat("sqlite").json_array_length("json_data", "family_list")
        self.assertEqual(
            expr,
            "json_array_length(json_extract(json_data, '$.family_list'))",
        )

    def test_sqlite_nested(self):
        expr = SQLCompat("sqlite").json_array_length(
            "json_data", "name.alt_list"
        )
        self.assertEqual(
            expr,
            "json_array_length(json_extract(json_data, '$.name.alt_list'))",
        )

    def test_postgresql_flat(self):
        expr = SQLCompat("postgresql").json_array_length(
            "json_data", "family_list"
        )
        self.assertEqual(
            expr, "json_array_length(((json_data::json)->'family_list'))"
        )

    def test_postgresql_nested(self):
        expr = SQLCompat("postgresql").json_array_length(
            "json_data", "name.alt_list"
        )
        self.assertEqual(
            expr,
            "json_array_length((((json_data::json)->'name')->'alt_list'))",
        )

    def test_sqlite_empty_array_detection(self):
        expr = SQLCompat("sqlite").json_array_length("json_data", "family_list")
        rows = _sqlite_exec(
            f"SELECT handle FROM person WHERE {expr} = 0"
        )
        # h1 has empty family_list, h2 has one entry
        self.assertEqual([r[0] for r in rows], ["h1"])

    def test_sqlite_non_empty_array_detection(self):
        expr = SQLCompat("sqlite").json_array_length(
            "json_data", "alternate_names"
        )
        rows = _sqlite_exec(
            f"SELECT handle FROM person WHERE {expr} > 0"
        )
        self.assertEqual([r[0] for r in rows], ["h2"])


class TestLimitOffset(unittest.TestCase):
    def test_both(self):
        self.assertEqual(
            SQLCompat("sqlite").limit_offset(10, 20), "LIMIT 10 OFFSET 20"
        )

    def test_limit_only(self):
        self.assertEqual(SQLCompat("sqlite").limit_offset(5), "LIMIT 5")

    def test_offset_only(self):
        self.assertEqual(SQLCompat("sqlite").limit_offset(offset=3), "OFFSET 3")

    def test_neither(self):
        self.assertEqual(SQLCompat("sqlite").limit_offset(), "")

    def test_same_on_both_dialects(self):
        s = SQLCompat("sqlite").limit_offset(100, 200)
        p = SQLCompat("postgresql").limit_offset(100, 200)
        self.assertEqual(s, p)

    def test_int_coercion(self):
        # Should not raise even if strings are passed (coerced via int())
        result = SQLCompat("sqlite").limit_offset("10", "20")
        self.assertEqual(result, "LIMIT 10 OFFSET 20")


class TestBooleanLiterals(unittest.TestCase):
    def test_sqlite_true(self):
        self.assertEqual(SQLCompat("sqlite").true(), "1")

    def test_sqlite_false(self):
        self.assertEqual(SQLCompat("sqlite").false(), "0")

    def test_postgresql_true(self):
        self.assertEqual(SQLCompat("postgresql").true(), "TRUE")

    def test_postgresql_false(self):
        self.assertEqual(SQLCompat("postgresql").false(), "FALSE")


class TestCoalesce(unittest.TestCase):
    def test_default_empty_string(self):
        expr = SQLCompat("sqlite").coalesce("given_name")
        self.assertEqual(expr, "COALESCE(given_name, '')")

    def test_custom_default(self):
        expr = SQLCompat("sqlite").coalesce("given_name", "0")
        self.assertEqual(expr, "COALESCE(given_name, 0)")

    def test_same_on_both_dialects(self):
        s = SQLCompat("sqlite").coalesce("surname")
        p = SQLCompat("postgresql").coalesce("surname")
        self.assertEqual(s, p)


if __name__ == "__main__":
    unittest.main()
