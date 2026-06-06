"""
Registration and fallback tests that require no backend-specific database.
"""

import unittest

from fastfilterslib.overload_rules import (
    DisconnectedOverride,
    HasAlternateNameOverride,
    IsFemaleOverride,
    IsMaleOverride,
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

    def test_hasalternatename_registered(self):
        self.assertIn(("person", "HasAlternateName"), self.registry)
        self.assertIs(
            self.registry[("person", "HasAlternateName")], HasAlternateNameOverride
        )

    def test_no_extra_registrations(self):
        self.assertEqual(len(self.registry), 4)


# ---------------------------------------------------------------------------
# Fallback tests (mock DB where json_data is unavailable)
# ---------------------------------------------------------------------------


class TestJsonDataFallback(unittest.TestCase):
    """Rules that need json_data delegate to the original when unavailable."""

    def _make_db(self, has_json):
        class _MockDB:
            dialect = "sqlite"

            def is_proxy(self):
                return False

            def use_json_data(self):
                return has_json

        return _MockDB()

    def test_disconnected_fallback_sets_no_handles(self):
        db = self._make_db(has_json=False)
        calls = []

        class _FakeRule:
            pass

        override = DisconnectedOverride(_FakeRule())

        def _original(rule, db, user):
            calls.append(True)

        override.prepare(_original, db, user=None)
        self.assertFalse(hasattr(override, "handles"))
        self.assertEqual(calls, [True])

    def test_disconnected_fallback_in_apply(self):
        class _FakeRule:
            pass

        override = DisconnectedOverride(_FakeRule())
        sentinel = object()
        result_store = []

        def _original(rule, db, obj):
            result_store.append(sentinel)
            return True

        result = override.apply_to_one(_original, db=None, person=object())
        self.assertTrue(result)
        self.assertEqual(result_store, [sentinel])

    def test_hasalternatename_fallback_sets_no_handles(self):
        db = self._make_db(has_json=False)
        calls = []

        class _FakeRule:
            pass

        override = HasAlternateNameOverride(_FakeRule())

        def _original(rule, db, user):
            calls.append(True)

        override.prepare(_original, db, user=None)
        self.assertFalse(hasattr(override, "handles"))
        self.assertEqual(calls, [True])


if __name__ == "__main__":
    unittest.main()
