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


class HasUnknownGenderOverride(RuleOverride):
    """Fast SQL replacement for person.HasUnknownGender."""

    def prepare(self, original, db, user):
        # gender is a secondary column: 0 = FEMALE, 1 = MALE, 2 = UNKNOWN
        self.handles = _fetch_handles(
            db, "SELECT handle FROM person WHERE gender = 2"
        )

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class HasOtherGenderOverride(RuleOverride):
    """Fast SQL replacement for person.HasOtherGender."""

    def prepare(self, original, db, user):
        # gender is a secondary column: 3 = OTHER
        self.handles = _fetch_handles(
            db, "SELECT handle FROM person WHERE gender = 3"
        )

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class NeverMarriedOverride(RuleOverride):
    """Fast SQL replacement for person.NeverMarried.

    A person has never married when their family_list in json_data is empty.
    Falls back to the original for blob-data databases.
    """

    def prepare(self, original, db, user):
        if not _needs_json_data(db):
            original(self.rule, db, user)
            return
        compat = SQLCompat.for_db(db)
        fl = compat.json_array_length("json_data", "family_list")
        sql = f"SELECT handle FROM person WHERE {fl} = 0"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        if not hasattr(self, "handles"):
            return original(self.rule, db, person)
        return person.handle in self.handles


class MultipleMarriagesOverride(RuleOverride):
    """Fast SQL replacement for person.MultipleMarriages.

    A person has multiple marriages when their family_list in json_data
    has more than one entry.  Falls back to the original for blob-data
    databases.
    """

    def prepare(self, original, db, user):
        if not _needs_json_data(db):
            original(self.rule, db, user)
            return
        compat = SQLCompat.for_db(db)
        fl = compat.json_array_length("json_data", "family_list")
        sql = f"SELECT handle FROM person WHERE {fl} > 1"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        if not hasattr(self, "handles"):
            return original(self.rule, db, person)
        return person.handle in self.handles


# ---------------------------------------------------------------------------
# Private / public overrides (all object types)
# ---------------------------------------------------------------------------


class _IsPrivateOverride(RuleOverride):
    """Base for all per-table private filter overrides.

    Subclasses set ``_table`` to the SQL table name for the relevant object
    type.  ``private`` is a secondary column (INTEGER, 0/1) on every table.
    """

    _table: str

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        self.handles = _fetch_handles(
            db, f"SELECT handle FROM {self._table} WHERE private = {compat.true()}"
        )

    def apply_to_one(self, original, db, obj):
        return obj.handle in self.handles


class PeoplePrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for person.PeoplePrivate."""

    _table = "person"


class PeoplePublicOverride(RuleOverride):
    """Fast SQL replacement for person.PeoplePublic."""

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        self.handles = _fetch_handles(
            db, f"SELECT handle FROM person WHERE private = {compat.false()}"
        )

    def apply_to_one(self, original, db, obj):
        return obj.handle in self.handles


class FamilyPrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for family.FamilyPrivate."""

    _table = "family"


class EventPrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for event.EventPrivate."""

    _table = "event"


class PlacePrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for place.PlacePrivate."""

    _table = "place"


class CitationPrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for citation.CitationPrivate."""

    _table = "citation"


class SourcePrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for source.SourcePrivate."""

    _table = "source"


class NotePrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for note.NotePrivate."""

    _table = "note"


class MediaPrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for media.MediaPrivate."""

    _table = "media"


class RepoPrivateOverride(_IsPrivateOverride):
    """Fast SQL replacement for repository.RepoPrivate."""

    _table = "repository"


# ---------------------------------------------------------------------------
# Place overrides
# ---------------------------------------------------------------------------


class HasNoLatOrLonOverride(RuleOverride):
    """Fast SQL replacement for place.HasNoLatOrLon.

    Matches places where lat or long is empty or whitespace-only, mirroring
    the Python rule which checks ``not place.lat.strip() or not place.long.strip()``.
    COALESCE guards against NULL in case the secondary column was added by
    an ALTER TABLE on an older database.
    """

    def prepare(self, original, db, user):
        self.handles = _fetch_handles(
            db,
            "SELECT handle FROM place"
            " WHERE TRIM(COALESCE(lat, '')) = ''"
            " OR TRIM(COALESCE(long, '')) = ''",
        )

    def apply_to_one(self, original, db, obj):
        return obj.handle in self.handles


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_rules(db):
    """Register all SQL-accelerated rule overrides with *db*."""
    # Person rules
    db.register_rule_override(("person", "IsMale"), IsMaleOverride)
    db.register_rule_override(("person", "IsFemale"), IsFemaleOverride)
    db.register_rule_override(("person", "Disconnected"), DisconnectedOverride)
    db.register_rule_override(("person", "HasAlternateName"), HasAlternateNameOverride)
    db.register_rule_override(("person", "HasUnknownGender"), HasUnknownGenderOverride)
    db.register_rule_override(("person", "HasOtherGender"), HasOtherGenderOverride)
    db.register_rule_override(("person", "NeverMarried"), NeverMarriedOverride)
    db.register_rule_override(("person", "MultipleMarriages"), MultipleMarriagesOverride)
    # Private / public rules (all object types)
    db.register_rule_override(("person", "PeoplePrivate"), PeoplePrivateOverride)
    db.register_rule_override(("person", "PeoplePublic"), PeoplePublicOverride)
    db.register_rule_override(("family", "FamilyPrivate"), FamilyPrivateOverride)
    db.register_rule_override(("event", "EventPrivate"), EventPrivateOverride)
    db.register_rule_override(("place", "PlacePrivate"), PlacePrivateOverride)
    db.register_rule_override(("citation", "CitationPrivate"), CitationPrivateOverride)
    db.register_rule_override(("source", "SourcePrivate"), SourcePrivateOverride)
    db.register_rule_override(("note", "NotePrivate"), NotePrivateOverride)
    db.register_rule_override(("media", "MediaPrivate"), MediaPrivateOverride)
    db.register_rule_override(("repository", "RepoPrivate"), RepoPrivateOverride)
    # Place rules
    db.register_rule_override(("place", "HasNoLatOrLon"), HasNoLatOrLonOverride)
