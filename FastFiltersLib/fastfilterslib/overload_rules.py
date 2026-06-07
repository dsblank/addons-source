"""
Filter rule overrides for SQLiteFastFilters.

Each override replaces the Python-object scan of the original rule with
a single SQL query that returns only the matching handles.  State is
precomputed in prepare() and cached in a frozenset so apply_to_one()
is a pure set-membership test.
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
    born into) are empty.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        fl = compat.json_array_length("json_data", "family_list")
        pfl = compat.json_array_length("json_data", "parent_family_list")
        sql = f"SELECT handle FROM person WHERE {fl} = 0 AND {pfl} = 0"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class HasNicknameOverride(RuleOverride):
    """Fast SQL replacement for person.HasNickname.

    Checks primary_name.nick only.  A person whose only nick lives in an
    alternate name or in a NICKNAME attribute will be a false negative
    (very rare in practice).
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        nick = compat.json_extract("json_data", "primary_name.nick")
        sql = f"SELECT handle FROM person WHERE TRIM(COALESCE({nick}, '')) != ''"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class HasAlternateNameOverride(RuleOverride):
    """Fast SQL replacement for person.HasAlternateName.

    A person has an alternate name when their alternate_names list in
    json_data is non-empty.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        al = compat.json_array_length("json_data", "alternate_names")
        sql = f"SELECT handle FROM person WHERE {al} > 0"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
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
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        fl = compat.json_array_length("json_data", "family_list")
        sql = f"SELECT handle FROM person WHERE {fl} = 0"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class MultipleMarriagesOverride(RuleOverride):
    """Fast SQL replacement for person.MultipleMarriages.

    A person has multiple marriages when their family_list in json_data
    has more than one entry.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        fl = compat.json_array_length("json_data", "family_list")
        sql = f"SELECT handle FROM person WHERE {fl} > 1"
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


# ---------------------------------------------------------------------------
# Tier 3 person overrides — single JOIN required
# ---------------------------------------------------------------------------


class MissingParentOverride(RuleOverride):
    """Fast SQL replacement for person.MissingParent.

    Matches persons who have no parent families, or whose parent family is
    missing a father or mother.  father_handle / mother_handle are secondary
    columns on the family table; parent_family_list is traversed via json_each.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        pfl_len = compat.json_array_length("p.json_data", "parent_family_list")
        pfl_from, pfl_val = compat.json_each_text(
            "p.json_data", "parent_family_list", "pfl"
        )
        sql = f"""
            SELECT p.handle
            FROM person p
            WHERE {pfl_len} = 0
               OR EXISTS (
                    SELECT 1
                    FROM {pfl_from}
                    JOIN family f ON f.handle = {pfl_val}
                    WHERE f.father_handle IS NULL OR f.father_handle = ''
                       OR f.mother_handle IS NULL OR f.mother_handle = ''
                  )
        """
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class HaveChildrenOverride(RuleOverride):
    """Fast SQL replacement for person.HaveChildren.

    Matches persons who are a spouse in at least one family that has children.
    family_list is traversed via json_each; child_ref_list length is read from
    family.json_data.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        fl_from, fl_val = compat.json_each_text("p.json_data", "family_list", "fl")
        crl_len = compat.json_array_length("f.json_data", "child_ref_list")
        sql = f"""
            SELECT p.handle
            FROM person p
            WHERE EXISTS (
                   SELECT 1
                   FROM {fl_from}
                   JOIN family f ON f.handle = {fl_val}
                   WHERE {crl_len} > 0
                 )
        """
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class NoBirthdateOverride(RuleOverride):
    """Fast SQL replacement for person.NoBirthdate.

    Matches persons who have no birth event, or whose birth event has no date
    (date.sortval == 0).  birth_ref_index is a secondary column; the event is
    located via a dynamic array-index path wrapped in CASE WHEN birth_ref_index
    >= 0 to prevent the -1 sentinel from being used as a path component (SQLite
    rejects negative JSON path indices; PostgreSQL treats them as reverse offsets).
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        birth_handle = compat.json_dynamic_array_field(
            "p.json_data", "event_ref_list", "p.birth_ref_index", "ref"
        )
        sortval = compat.json_extract_int("e.json_data", "date.sortval")
        sql = f"""
            SELECT p.handle
            FROM person p
            LEFT JOIN event e ON e.handle = CASE
                WHEN p.birth_ref_index >= 0 THEN {birth_handle}
                ELSE NULL
            END
            WHERE COALESCE({sortval}, 0) = 0
        """
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class NoDeathdateOverride(RuleOverride):
    """Fast SQL replacement for person.NoDeathdate.

    Identical structure to NoBirthdateOverride, using death_ref_index instead
    of birth_ref_index.  Same CASE WHEN guard applies.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        death_handle = compat.json_dynamic_array_field(
            "p.json_data", "event_ref_list", "p.death_ref_index", "ref"
        )
        sortval = compat.json_extract_int("e.json_data", "date.sortval")
        sql = f"""
            SELECT p.handle
            FROM person p
            LEFT JOIN event e ON e.handle = CASE
                WHEN p.death_ref_index >= 0 THEN {death_handle}
                ELSE NULL
            END
            WHERE COALESCE({sortval}, 0) = 0
        """
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


# ---------------------------------------------------------------------------
# Tier 3+ person overrides — complex SQL or SQL + Python hybrid
# ---------------------------------------------------------------------------


class HaveAltFamiliesOverride(RuleOverride):
    """Fast SQL replacement for person.HaveAltFamilies (adopted people).

    Matches persons who appear in a parent family's child_ref_list with an
    ADOPTED (value=2) father or mother relation.  Uses nested EXISTS:
    outer iterates parent_family_list; inner iterates child_ref_list filtered
    to this person's handle and checks frel/mrel value.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        pfl_from, pfl_val = compat.json_each_text(
            "p.json_data", "parent_family_list", "pfl"
        )
        crl_from, crl_val = compat.json_each_json(
            "f.json_data", "child_ref_list", "crl"
        )
        ref = compat.json_extract(crl_val, "ref")
        frel = compat.json_extract_int(crl_val, "frel.value")
        mrel = compat.json_extract_int(crl_val, "mrel.value")
        sql = f"""
            SELECT p.handle
            FROM person p
            WHERE EXISTS (
                SELECT 1
                FROM {pfl_from}
                JOIN family f ON f.handle = {pfl_val}
                WHERE EXISTS (
                    SELECT 1
                    FROM {crl_from}
                    WHERE {ref} = p.handle
                      AND ({frel} = 2 OR {mrel} = 2)
                )
            )
        """
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        return person.handle in self.handles


class IncompleteNamesOverride(RuleOverride):
    """SQL + Python hybrid replacement for person.IncompleteNames.

    SQL pre-selects persons with an incomplete primary name (blank first_name,
    empty surname_list, or a blank surname entry).  Python post-checks alternate
    names for the remaining persons, since those are very rarely incomplete and
    nested SQL over alternate_names → surname_list would be expensive.
    """

    def prepare(self, original, db, user):
        compat = SQLCompat.for_db(db)
        first = compat.json_extract("json_data", "primary_name.first_name")
        slist_len = compat.json_array_length("json_data", "primary_name.surname_list")
        sn_from, sn_val = compat.json_each_json(
            "json_data", "primary_name.surname_list", "sn"
        )
        surname = compat.json_extract(sn_val, "surname")
        sql = f"""
            SELECT handle FROM person
            WHERE TRIM(COALESCE({first}, '')) = ''
               OR {slist_len} = 0
               OR EXISTS (
                    SELECT 1
                    FROM {sn_from}
                    WHERE TRIM(COALESCE({surname}, '')) = ''
                  )
        """
        self.handles = _fetch_handles(db, sql)

    def apply_to_one(self, original, db, person):
        if person.handle in self.handles:
            return True
        for name in person.alternate_names:
            if name.first_name.strip() == "":
                return True
            if name.surname_list:
                for surn in name.surname_list:
                    if surn.surname.strip() == "":
                        return True
            else:
                return True
        return False


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
    db.register_rule_override(("person", "HasNickname"), HasNicknameOverride)
    db.register_rule_override(("person", "HasAlternateName"), HasAlternateNameOverride)
    db.register_rule_override(("person", "HasUnknownGender"), HasUnknownGenderOverride)
    db.register_rule_override(("person", "HasOtherGender"), HasOtherGenderOverride)
    db.register_rule_override(("person", "NeverMarried"), NeverMarriedOverride)
    db.register_rule_override(("person", "MultipleMarriages"), MultipleMarriagesOverride)
    # Tier 3 person rules — single JOIN
    db.register_rule_override(("person", "MissingParent"), MissingParentOverride)
    db.register_rule_override(("person", "HaveChildren"), HaveChildrenOverride)
    db.register_rule_override(("person", "NoBirthdate"), NoBirthdateOverride)
    db.register_rule_override(("person", "NoDeathdate"), NoDeathdateOverride)
    # Tier 3+ person rules — complex SQL or hybrid
    db.register_rule_override(("person", "HaveAltFamilies"), HaveAltFamiliesOverride)
    db.register_rule_override(("person", "IncompleteNames"), IncompleteNamesOverride)
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
