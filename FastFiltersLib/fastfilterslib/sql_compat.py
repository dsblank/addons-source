"""
SQL dialect compatibility layer for SQLiteFastFilters.

Generates dialect-appropriate SQL fragments so that filter overrides
can target both SQLite and PostgreSQL without branching in rule code.
"""


class SQLCompat:
    """
    Build SQL fragments that work on SQLite or PostgreSQL.

    Usage:
        compat = SQLCompat.for_db(db)
        sql = f"SELECT handle FROM person WHERE {compat.json_array_length('json_data', 'family_list')} = 0"
    """

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"

    def __init__(self, dialect):
        if dialect not in (self.SQLITE, self.POSTGRESQL):
            raise ValueError(
                f"Unknown SQL dialect: {dialect!r}. Use 'sqlite' or 'postgresql'."
            )
        self.dialect = dialect

    @classmethod
    def for_db(cls, db):
        """Create a SQLCompat instance from a database object."""
        return cls(getattr(db, "dialect", cls.SQLITE))

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def placeholder(self):
        """Return the positional parameter placeholder for this dialect."""
        return "?" if self.dialect == self.SQLITE else "%s"

    # ------------------------------------------------------------------
    # Pattern matching
    # ------------------------------------------------------------------

    def regexp(self, column, pattern_expr):
        """
        Return a regex-match SQL expression.

        column      : column name or expression
        pattern_expr: a SQL expression for the pattern (e.g. placeholder())

        SQLite:     regexp(<pattern>, <column>)
        PostgreSQL: <column> ~ <pattern>
        """
        if self.dialect == self.SQLITE:
            return f"regexp({pattern_expr}, {column})"
        return f"{column} ~ {pattern_expr}"

    def ilike(self, column, pattern_expr):
        """
        Return a case-insensitive LIKE expression.

        SQLite:     lower(<column>) LIKE lower(<pattern>)
        PostgreSQL: <column> ILIKE <pattern>
        """
        if self.dialect == self.SQLITE:
            return f"lower({column}) LIKE lower({pattern_expr})"
        return f"{column} ILIKE {pattern_expr}"

    # ------------------------------------------------------------------
    # JSON access
    # ------------------------------------------------------------------

    def json_extract(self, column, path):
        """
        Extract a scalar value from a JSON column.

        path: dot-separated field path, e.g. 'primary_name.first_name'

        SQLite:     json_extract(<col>, '$.<path>')
        PostgreSQL: navigates with -> / ->> operators
        """
        if self.dialect == self.SQLITE:
            return f"json_extract({column}, '$.{path}')"
        # PostgreSQL: chain -> for all but the last segment, ->> for the leaf
        parts = path.split(".")
        expr = f"({column}::json)"
        for part in parts[:-1]:
            expr = f"({expr}->'{part}')"
        return f"{expr}->>'{parts[-1]}'"

    def json_array_length(self, column, path):
        """
        Return the length of a JSON array at the given path.

        path: dot-separated field path, e.g. 'family_list'

        SQLite:     json_array_length(json_extract(<col>, '$.<path>'))
        PostgreSQL: json_array_length((<col>::json)->'<path>')
        """
        if self.dialect == self.SQLITE:
            return f"json_array_length(json_extract({column}, '$.{path}'))"
        parts = path.split(".")
        expr = f"({column}::json)"
        for part in parts:
            expr = f"({expr}->'{part}')"
        return f"json_array_length({expr})"

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def limit_offset(self, limit=None, offset=None):
        """
        Return a LIMIT / OFFSET clause.  Syntax is identical on both
        dialects, but this helper keeps callers uniform.
        """
        parts = []
        if limit is not None:
            parts.append(f"LIMIT {int(limit)}")
        if offset is not None:
            parts.append(f"OFFSET {int(offset)}")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Boolean literals
    # ------------------------------------------------------------------

    def true(self):
        """Boolean true literal (used in generated SQL, not parameters)."""
        return "1" if self.dialect == self.SQLITE else "TRUE"

    def false(self):
        """Boolean false literal."""
        return "0" if self.dialect == self.SQLITE else "FALSE"

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def coalesce(self, expr, default="''"):
        """Return expr, substituting default when NULL."""
        return f"COALESCE({expr}, {default})"
