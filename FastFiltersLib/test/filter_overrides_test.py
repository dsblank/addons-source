"""
Registration tests that require no backend-specific database.
"""

import unittest

from fastfilterslib.overload_rules import (
    CitationPrivateOverride,
    DisconnectedOverride,
    EventPrivateOverride,
    FamilyPrivateOverride,
    HasAlternateNameOverride,
    HasNicknameOverride,
    HasNoLatOrLonOverride,
    HasOtherGenderOverride,
    HasUnknownGenderOverride,
    HaveAltFamiliesOverride,
    HaveChildrenOverride,
    IncompleteNamesOverride,
    IsFemaleOverride,
    IsMaleOverride,
    MediaPrivateOverride,
    MissingParentOverride,
    MultipleMarriagesOverride,
    NeverMarriedOverride,
    NoBirthdateOverride,
    NoDeathdateOverride,
    NotePrivateOverride,
    PeoplePrivateOverride,
    PeoplePublicOverride,
    PlacePrivateOverride,
    RepoPrivateOverride,
    SourcePrivateOverride,
    register_rules,
)


# ---------------------------------------------------------------------------
# Registration tests (mock DB only)
# ---------------------------------------------------------------------------


class TestRegistration(unittest.TestCase):
    """register_rules() wires up exactly the expected keys."""

    def setUp(self):
        class _MockDB:
            def __init__(self):
                self._override_registry = {}
                self.dialect = "sqlite"

            def is_proxy(self):
                return False

            def register_rule_override(self, key, cls):
                self._override_registry.setdefault("rule", {})[key] = cls

        self.db = _MockDB()
        register_rules(self.db)
        self.registry = self.db._override_registry.get("rule", {})

    def test_ismale_registered(self):
        self.assertIn(("person", "IsMale"), self.registry)
        self.assertIs(self.registry[("person", "IsMale")], IsMaleOverride)

    def test_isfemale_registered(self):
        self.assertIn(("person", "IsFemale"), self.registry)
        self.assertIs(self.registry[("person", "IsFemale")], IsFemaleOverride)

    def test_disconnected_registered(self):
        self.assertIn(("person", "Disconnected"), self.registry)
        self.assertIs(self.registry[("person", "Disconnected")], DisconnectedOverride)

    def test_hasnickname_registered(self):
        self.assertIn(("person", "HasNickname"), self.registry)
        self.assertIs(self.registry[("person", "HasNickname")], HasNicknameOverride)

    def test_hasalternatename_registered(self):
        self.assertIn(("person", "HasAlternateName"), self.registry)
        self.assertIs(
            self.registry[("person", "HasAlternateName")], HasAlternateNameOverride
        )

    def test_hasunknowngender_registered(self):
        self.assertIn(("person", "HasUnknownGender"), self.registry)
        self.assertIs(
            self.registry[("person", "HasUnknownGender")], HasUnknownGenderOverride
        )

    def test_hasothergender_registered(self):
        self.assertIn(("person", "HasOtherGender"), self.registry)
        self.assertIs(
            self.registry[("person", "HasOtherGender")], HasOtherGenderOverride
        )

    def test_nevermarried_registered(self):
        self.assertIn(("person", "NeverMarried"), self.registry)
        self.assertIs(self.registry[("person", "NeverMarried")], NeverMarriedOverride)

    def test_multiplemarriages_registered(self):
        self.assertIn(("person", "MultipleMarriages"), self.registry)
        self.assertIs(
            self.registry[("person", "MultipleMarriages")], MultipleMarriagesOverride
        )

    def test_peopleprivate_registered(self):
        self.assertIn(("person", "PeoplePrivate"), self.registry)
        self.assertIs(self.registry[("person", "PeoplePrivate")], PeoplePrivateOverride)

    def test_peoplepublic_registered(self):
        self.assertIn(("person", "PeoplePublic"), self.registry)
        self.assertIs(self.registry[("person", "PeoplePublic")], PeoplePublicOverride)

    def test_familyprivate_registered(self):
        self.assertIn(("family", "FamilyPrivate"), self.registry)
        self.assertIs(self.registry[("family", "FamilyPrivate")], FamilyPrivateOverride)

    def test_eventprivate_registered(self):
        self.assertIn(("event", "EventPrivate"), self.registry)
        self.assertIs(self.registry[("event", "EventPrivate")], EventPrivateOverride)

    def test_placeprivate_registered(self):
        self.assertIn(("place", "PlacePrivate"), self.registry)
        self.assertIs(self.registry[("place", "PlacePrivate")], PlacePrivateOverride)

    def test_citationprivate_registered(self):
        self.assertIn(("citation", "CitationPrivate"), self.registry)
        self.assertIs(
            self.registry[("citation", "CitationPrivate")], CitationPrivateOverride
        )

    def test_sourceprivate_registered(self):
        self.assertIn(("source", "SourcePrivate"), self.registry)
        self.assertIs(self.registry[("source", "SourcePrivate")], SourcePrivateOverride)

    def test_noteprivate_registered(self):
        self.assertIn(("note", "NotePrivate"), self.registry)
        self.assertIs(self.registry[("note", "NotePrivate")], NotePrivateOverride)

    def test_mediaprivate_registered(self):
        self.assertIn(("media", "MediaPrivate"), self.registry)
        self.assertIs(self.registry[("media", "MediaPrivate")], MediaPrivateOverride)

    def test_repoprivate_registered(self):
        self.assertIn(("repository", "RepoPrivate"), self.registry)
        self.assertIs(self.registry[("repository", "RepoPrivate")], RepoPrivateOverride)

    def test_hasnolatorlon_registered(self):
        self.assertIn(("place", "HasNoLatOrLon"), self.registry)
        self.assertIs(
            self.registry[("place", "HasNoLatOrLon")], HasNoLatOrLonOverride
        )

    def test_missingparent_registered(self):
        self.assertIn(("person", "MissingParent"), self.registry)
        self.assertIs(self.registry[("person", "MissingParent")], MissingParentOverride)

    def test_havechildren_registered(self):
        self.assertIn(("person", "HaveChildren"), self.registry)
        self.assertIs(self.registry[("person", "HaveChildren")], HaveChildrenOverride)

    def test_nobirthdate_registered(self):
        self.assertIn(("person", "NoBirthdate"), self.registry)
        self.assertIs(self.registry[("person", "NoBirthdate")], NoBirthdateOverride)

    def test_nodeathdate_registered(self):
        self.assertIn(("person", "NoDeathdate"), self.registry)
        self.assertIs(self.registry[("person", "NoDeathdate")], NoDeathdateOverride)

    def test_havealtfamilies_registered(self):
        self.assertIn(("person", "HaveAltFamilies"), self.registry)
        self.assertIs(
            self.registry[("person", "HaveAltFamilies")], HaveAltFamiliesOverride
        )

    def test_incompletenames_registered(self):
        self.assertIn(("person", "IncompleteNames"), self.registry)
        self.assertIs(
            self.registry[("person", "IncompleteNames")], IncompleteNamesOverride
        )

    def test_no_extra_registrations(self):
        self.assertEqual(len(self.registry), 26)


if __name__ == "__main__":
    unittest.main()
