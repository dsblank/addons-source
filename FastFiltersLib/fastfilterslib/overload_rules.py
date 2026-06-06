"""
Filter rule overrides for SQLiteFastFilters.

Each override replaces the Python-object scan of the original rule with
a single SQL query that returns only the matching handles.  State is
precomputed in prepare() and cached in a frozenset so apply_to_one()
is a pure set-membership test.

Rules that need json_data access gracefully fall back to the original
Python implementation when the database is in blob-data mode.
"""

from gramps.gen.filters.rules._rule import RuleOverride
from fastfilterslib.sql_compat import SQLCompat


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_handles(db, sql, params=()):
    """Execute *sql* and return a frozenset of the first column of every row."""
    if params:
        db.dbapi.execute(sql, list(params))
    else:
        db.dbapi.execute(sql)
    return frozenset(row[0] for row in db.dbapi.fetchall())


def _needs_json_data(db):
    """Return True when the database stores data as JSON (not blobs)."""
    return db.use_json_data()


# ---------------------------------------------------------------------------
# Person overrides
# ---------------------------------------------------------------------------


class IsMaleOverride(RuleOverride):
    """Fast SQL replacement for person.IsMale."""

    def prepare(self, original, db, user):
        # gender is a secondary column: 1 = MALE, 0 = FEMALE, 2 = UNKNOWN
        self.handles = _fetch_handles(
            db, "SELECT handle FROM person WHERE gender = 1"
        )

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class IsFemaleOverride(RuleOverride):
    """Fast SQL replacement for person.IsFemale."""

    def prepare(self, original, db, user):
        self.handles = _fetch_handles(
            db, "SELECT handle FROM person WHERE gender = 0"
        )

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class DisconnectedOverride(RuleOverride):
    """Fast SQL replacement for person.Disconnected.

    A person is disconnected when both their family_list (families they
    are a spouse/partner in) and parent_family_list (families they were
    born into) are empty.  These lists live in json_data, so blob-data
    databases fall back to the original implementation.
    """

    def prepare(self, original, db, user):
        if not _needs_json_data(db):
            original(self.rule, db, user)
            return
        compat = SQLCompat.for_db(db)
        fl = compat.json_array_length("json_data", "family_list")
        pfl = compat.json_array_length("json_data", "parent_family_list")
        sql = f"SELECT handle FROM person WHERE {fl} = 0 AND {pfl} = 0"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        if not hasattr(self, "handles"):
            return original(self.rule, db, person)
        return person.handle in self.handles


class HasAlternateNameOverride(RuleOverride):
    """Fast SQL replacement for person.HasAlternateName.

    A person has an alternate name when their alternate_names list in
    json_data is non-empty.  Falls back to the original for blob-data
    databases.
    """

    def prepare(self, original, db, user):
        if not _needs_json_data(db):
            original(self.rule, db, user)
            return
        compat = SQLCompat.for_db(db)
        al = compat.json_array_length("json_data", "alternate_names")
        sql = f"SELECT handle FROM person WHERE {al} > 0"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        if not hasattr(self, "handles"):
            return original(self.rule, db, person)
        return person.handle in self.handles


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_rules(db):
    """Register all SQL-accelerated rule overrides with *db*."""
    db.register_rule_override(("person", "IsMale"), IsMaleOverride)
    db.register_rule_override(("person", "IsFemale"), IsFemaleOverride)
    db.register_rule_override(("person", "Disconnected"), DisconnectedOverride)
    db.register_rule_override(("person", "HasAlternateName"), HasAlternateNameOverride)
