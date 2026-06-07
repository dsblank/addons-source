"""
Shared test mixins for filter override integration tests.

Each mixin contains backend-agnostic test methods.  Concrete test classes in
SQLiteFastFilters and PostgreSQLFastFilters subclass these mixins and supply
_open_db() to return a live database of the appropriate type.
"""

import os
import unittest

from gramps.gen.const import TEST_DIR
from gramps.gen.filters import GenericFilter, GenericFilterFactory
from gramps.gen.filters.rules.citation import CitationPrivate
from gramps.gen.filters.rules.event import EventPrivate
from gramps.gen.filters.rules.family import FamilyPrivate
from gramps.gen.filters.rules.media import MediaPrivate
from gramps.gen.filters.rules.note import NotePrivate
from gramps.gen.filters.rules.person import (
    Disconnected,
    HasAlternateName,
    HasNickname,
    HasOtherGender,
    HasUnknownGender,
    IsFemale,
    IsMale,
    MultipleMarriages,
    NeverMarried,
    PeoplePrivate,
    PeoplePublic,
)
from gramps.gen.filters.rules.place import HasNoLatOrLon, PlacePrivate
from gramps.gen.filters.rules.repository import RepoPrivate
from gramps.gen.filters.rules.source import SourcePrivate
from gramps.gen.db import DbTxn
from gramps.gen.lib import (
    Citation,
    Event,
    Family,
    Media,
    Name,
    Note,
    Person,
    Place,
    Repository,
    Source,
    Surname,
)

from fastfilterslib.overload_rules import (
    IsMaleOverride,
    register_rules,
)

EXAMPLE = os.path.join(TEST_DIR, "example.gramps")


# ---------------------------------------------------------------------------
# Helpers shared across all mixins
# ---------------------------------------------------------------------------


def _make_person(gender, family_handles=(), parent_family_handles=(), alt_names=(), nick=""):
    """Return a Person object pre-populated with the given attributes."""
    p = Person()
    p.set_gender(gender)
    for h in family_handles:
        p.add_family_handle(h)
    for h in parent_family_handles:
        p.add_parent_family_handle(h)
    for name_str in alt_names:
        n = Name()
        sn = Surname()
        sn.set_surname(name_str)
        n.add_surname(sn)
        p.add_alternate_name(n)
    if nick:
        p.primary_name.set_nick_name(nick)
    return p


def _commit(db, obj):
    """Commit *obj* to *db* and return its handle."""
    with DbTxn("test", db) as txn:
        cls_name = type(obj).__name__.lower()
        getattr(db, f"add_{cls_name}")(obj, txn)
    return obj.handle


def _apply(db, rule, namespace="Person"):
    """Run a single-rule filter for *namespace* and return a set of handles."""
    f = GenericFilterFactory(namespace)()
    f.add_rule(rule)
    return set(f.apply(db))


# ---------------------------------------------------------------------------
# SmallDatabaseTestsMixin
# ---------------------------------------------------------------------------


class SmallDatabaseTestsMixin:
    """
    Tests against a small hand-built database with known people.

    Subclasses must implement _open_db() returning an empty, open DBAPI db.
    """

    @classmethod
    def _open_db(cls):
        raise NotImplementedError

    @classmethod
    def setUpClass(cls):
        cls.db = cls._open_db()

        cls.h_male_disconnected = _commit(cls.db, _make_person(Person.MALE))
        cls.h_female_connected = _commit(
            cls.db, _make_person(Person.FEMALE, family_handles=["fam1"])
        )
        cls.h_unknown_connected = _commit(
            cls.db, _make_person(Person.UNKNOWN, parent_family_handles=["fam2"])
        )
        cls.h_male_altname = _commit(
            cls.db, _make_person(Person.MALE, alt_names=["Smith"])
        )
        cls.h_female_altname = _commit(
            cls.db, _make_person(Person.FEMALE, alt_names=["Jones"])
        )
        cls.h_other_connected = _commit(
            cls.db, _make_person(Person.OTHER, family_handles=["fam_other"])
        )
        cls.h_with_nick = _commit(
            cls.db, _make_person(Person.MALE, nick="Bubba")
        )
        register_rules(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _apply(self, rule):
        return _apply(self.db, rule)

    def test_ismale_returns_only_males(self):
        result = self._apply(IsMale([]))
        self.assertIn(self.h_male_disconnected, result)
        self.assertIn(self.h_male_altname, result)
        self.assertNotIn(self.h_female_connected, result)
        self.assertNotIn(self.h_female_altname, result)
        self.assertNotIn(self.h_unknown_connected, result)
        self.assertNotIn(self.h_other_connected, result)

    def test_ismale_count(self):
        self.assertEqual(len(self._apply(IsMale([]))), 3)

    def test_isfemale_returns_only_females(self):
        result = self._apply(IsFemale([]))
        self.assertIn(self.h_female_connected, result)
        self.assertIn(self.h_female_altname, result)
        self.assertNotIn(self.h_male_disconnected, result)
        self.assertNotIn(self.h_male_altname, result)
        self.assertNotIn(self.h_unknown_connected, result)

    def test_ismale_and_isfemale_are_disjoint(self):
        males = self._apply(IsMale([]))
        females = self._apply(IsFemale([]))
        self.assertEqual(males & females, set())

    def test_disconnected_returns_persons_with_no_families(self):
        result = self._apply(Disconnected([]))
        self.assertIn(self.h_male_disconnected, result)
        self.assertIn(self.h_male_altname, result)
        self.assertIn(self.h_female_altname, result)
        self.assertNotIn(self.h_female_connected, result)
        self.assertNotIn(self.h_unknown_connected, result)

    def test_disconnected_count(self):
        self.assertEqual(len(self._apply(Disconnected([]))), 4)

    def test_hasalternatename_returns_persons_with_alt_names(self):
        result = self._apply(HasAlternateName([]))
        self.assertIn(self.h_male_altname, result)
        self.assertIn(self.h_female_altname, result)
        self.assertNotIn(self.h_male_disconnected, result)
        self.assertNotIn(self.h_female_connected, result)
        self.assertNotIn(self.h_unknown_connected, result)

    def test_hasalternatename_count(self):
        self.assertEqual(len(self._apply(HasAlternateName([]))), 2)

    def test_hasunknowngender_returns_only_unknown(self):
        result = self._apply(HasUnknownGender([]))
        self.assertIn(self.h_unknown_connected, result)
        self.assertNotIn(self.h_male_disconnected, result)
        self.assertNotIn(self.h_female_connected, result)
        self.assertNotIn(self.h_other_connected, result)

    def test_hasunknowngender_count(self):
        self.assertEqual(len(self._apply(HasUnknownGender([]))), 1)

    def test_hasothergender_returns_only_other(self):
        result = self._apply(HasOtherGender([]))
        self.assertIn(self.h_other_connected, result)
        self.assertNotIn(self.h_male_disconnected, result)
        self.assertNotIn(self.h_female_connected, result)
        self.assertNotIn(self.h_unknown_connected, result)

    def test_hasothergender_count(self):
        self.assertEqual(len(self._apply(HasOtherGender([]))), 1)

    def test_gender_filters_cover_all_people(self):
        total = self.db.get_number_of_people()
        males = len(self._apply(IsMale([])))
        females = len(self._apply(IsFemale([])))
        unknown = len(self._apply(HasUnknownGender([])))
        other = len(self._apply(HasOtherGender([])))
        self.assertEqual(males + females + unknown + other, total)

    def test_nevermarried_returns_persons_with_no_spouse_families(self):
        result = self._apply(NeverMarried([]))
        # family_list empty → never married
        self.assertIn(self.h_male_disconnected, result)
        self.assertIn(self.h_unknown_connected, result)  # has parent_family but no family
        self.assertIn(self.h_male_altname, result)
        self.assertIn(self.h_female_altname, result)
        # family_list non-empty → not never married
        self.assertNotIn(self.h_female_connected, result)
        self.assertNotIn(self.h_other_connected, result)

    def test_nevermarried_count(self):
        self.assertEqual(len(self._apply(NeverMarried([]))), 5)

    def test_multiplemarriages_returns_persons_with_multiple_families(self):
        result = self._apply(MultipleMarriages([]))
        # no one in the small DB has > 1 family
        self.assertEqual(result, set())

    def test_nevermarried_and_multiplemarriages_are_disjoint(self):
        never = self._apply(NeverMarried([]))
        multi = self._apply(MultipleMarriages([]))
        self.assertEqual(never & multi, set())

    def test_hasnickname_returns_persons_with_nick(self):
        result = self._apply(HasNickname([]))
        self.assertIn(self.h_with_nick, result)
        self.assertNotIn(self.h_male_disconnected, result)
        self.assertNotIn(self.h_female_connected, result)

    def test_hasnickname_count(self):
        self.assertEqual(len(self._apply(HasNickname([]))), 1)


# ---------------------------------------------------------------------------
# ExampleDatabaseTestsMixin
# ---------------------------------------------------------------------------


class ExampleDatabaseTestsMixin:
    """
    Tests against example.gramps with known expected values from the
    Gramps core person_rules_test suite.

    Subclasses must implement _open_db() returning a DBAPI db already
    loaded with the example.gramps data.
    """

    @classmethod
    def _open_db(cls):
        raise NotImplementedError

    @classmethod
    def setUpClass(cls):
        cls.db = cls._open_db()
        register_rules(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _apply(self, rule):
        return _apply(self.db, rule)

    def test_ismale_count_matches_expected(self):
        self.assertEqual(len(self._apply(IsMale([]))), 1168)

    def test_isfemale_count_matches_expected(self):
        self.assertEqual(len(self._apply(IsFemale([]))), 940)

    def test_ismale_isfemale_disjoint(self):
        males = self._apply(IsMale([]))
        females = self._apply(IsFemale([]))
        self.assertEqual(males & females, set())

    def test_ismale_isfemale_cover_all_gendered(self):
        total = self.db.get_number_of_people()
        males = len(self._apply(IsMale([])))
        females = len(self._apply(IsFemale([])))
        self.assertLessEqual(males + females, total)

    def test_disconnected_matches_expected_handles(self):
        expected = {
            "0PBKQCXHLAEIB46ZIA",
            "QEVJQC04YO01UAWJ2N",
            "UT0KQCMN7PC9XURRXJ",
            "MZAKQCKAQLIQYWP5IW",
            "Y7BKQC9CUXWQLGLPQM",
            "OBBKQC8NJM5UYBO849",
            "NPBKQCKEF0G7T4H312",
            "423KQCGLT8UISDUM1Q",
            "8S0KQCNORIWDL0X8SB",
            "AP5KQC0LBXPM727OWB",
            "AREKQC0VPBHNZ5R3IO",
            "KU0KQCJ0RUTJTIUKSA",
            "VC4KQC7L7KKH9RLHXN",
            "0P3KQCRSIVL1A4VJ19",
            "PK6KQCGEL4PTE720BL",
            "YIKKQCSD2Z85UHJ8LX",
            "KY8KQCMIH2HUUGLA3R",
            "RD7KQCQ24B1N3OEC5X",
            "NV0KQC7SIEH3SVDPP1",
            "KIKKQCU2CJ543TLM5J",
            "AT0KQC4P3MMUCHI3BK",
            "J6BKQC1PMNBAYSLM9U",
            "IXXJQCLKOUAJ5RSQY4",
            "U4ZJQC5VR0QBIE8DU",
            "F7BKQC4NXO9R7XOG2W",
            "7U0KQC6PGZBNQATNOT",
            "78AKQCI05U36T3E82O",
            "H1GKQCWOUJHFSHXABA",
            "ZWGKQCRFZAPC5PYJZ1",
            "EZ0KQCF3LSM9PRSG0K",
            "FHKKQC963NGSY18ZDZ",
            "FJ9KQCRJ3RGHNBWW4S",
            "S2EKQC9F4UR4R71IC3",
            "1XBKQCX019BKJ0M9IH",
            "Z62KQC706L0B0WTN3Q",
            "O7EKQCEVZ7FBEWMNWE",
            "XY8KQCULFPN4SR915Q",
            "WQDKQCEULSD5G9XNFI",
            "2Z0KQCSWKVFG7RPFD8",
            "26BKQC0SJIJOH02H2A",
            "262KQCH2RQKN0CBRLF",
            "P5ZJQCMKO7EYV4HFCL",
            "KXBKQC52JO3AP4GMLF",
            "9IFKQC60JTDBV57N6S",
            "TQ0KQCZ8LA7X9DIEAN",
            "BAXJQCORQA5Q46FCDG",
            "VR0KQC7LVANO83AL35",
            "75CKQC4T617U2E5T5Y",
            "LCTKQCZU3F94CEFSOM",
            "WJYJQCPNJJI5JN07SD",
            "3N6KQC6BE5EIXTRMDL",
            "CM5KQCD57I15GKLAMB",
            "cccbffffd3e69819cd8",
            "BJKKQCVDA66528PDAU",
            "QS0KQCLMIZFI8ZDLM3",
            "UW0KQCRHBIYMA8LPZD",
            "GJ7KQC7APJSAMHEK5Q",
            "711KQCDXOQWB3KDWEP",
            "PY0KQC77AJ3457A6C2",
            "WZ0KQCYVMEJHDR4MV2",
            "28EKQCQGM6NLLWFRG7",
            "E33KQCRREJALRA715H",
            "8HKKQCTEJAOBVH410L",
            "IO6KQC70PMBQUDNB3L",
            "1YBKQCWRBNB433NEMH",
            "M01KQCF7KUWCDY67JD",
            "CR0KQCOMV2QPPC90IF",
            "85ZJQCMG38N7Q2WKIK",
            "I9GKQCERACL8UZF2PY",
            "BY0KQCOZUK47R2JZDE",
            "7W0KQCYDMD4LTSY5JL",
            "A0YJQC3HONEKD1JCPK",
            "d5839c13b0541b7b8e6",
        }
        self.assertEqual(self._apply(Disconnected([])), expected)

    def test_hasalternatename_matches_expected_handles(self):
        expected = {"46WJQCIOLQ0KOX2XCC", "GNUJQCL9MD64AM56OH"}
        self.assertEqual(self._apply(HasAlternateName([])), expected)

    def test_gender_filters_cover_all_people(self):
        total = self.db.get_number_of_people()
        males = len(self._apply(IsMale([])))
        females = len(self._apply(IsFemale([])))
        unknown = len(self._apply(HasUnknownGender([])))
        other = len(self._apply(HasOtherGender([])))
        self.assertEqual(males + females + unknown + other, total)

    def test_nevermarried_and_multiplemarriages_are_disjoint(self):
        never = self._apply(NeverMarried([]))
        multi = self._apply(MultipleMarriages([]))
        self.assertEqual(never & multi, set())

    def test_nevermarried_and_multiplemarriages_cover_subset_of_total(self):
        total = self.db.get_number_of_people()
        never = len(self._apply(NeverMarried([])))
        multi = len(self._apply(MultipleMarriages([])))
        self.assertLessEqual(never + multi, total)

    def test_hasnickname_result_is_subset_of_python_result(self):
        # SQL checks primary_name.nick only (approximation); result must be a
        # subset of the full Python result (no false positives allowed).
        python_expected = {
            "cc8205d883763f02abd",
            "GNUJQCL9MD64AM56OH",
            "Q8HKQC3VMRM1M6M7ES",
        }
        result = self._apply(HasNickname([]))
        self.assertTrue(result.issubset(python_expected))
        self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# SQLPathTestsMixin
# ---------------------------------------------------------------------------


class SQLPathTestsMixin:
    """
    Verify that the SQL override path is taken by inspecting
    rule._db_override.handles after a filter run.

    Subclasses must implement _open_db() returning an empty, open DBAPI db.
    """

    @classmethod
    def _open_db(cls):
        raise NotImplementedError

    @classmethod
    def setUpClass(cls):
        cls.db = cls._open_db()
        cls.h_male = _commit(cls.db, _make_person(Person.MALE))
        cls.h_female = _commit(cls.db, _make_person(Person.FEMALE))
        cls.h_with_altname = _commit(
            cls.db, _make_person(Person.UNKNOWN, alt_names=["AltName"])
        )
        cls.h_connected = _commit(
            cls.db, _make_person(Person.UNKNOWN, family_handles=["fam1"])
        )
        cls.h_other = _commit(
            cls.db, _make_person(Person.OTHER, family_handles=["fam_other"])
        )
        cls.h_multi = _commit(
            cls.db, _make_person(Person.MALE, family_handles=["fam2", "fam3"])
        )
        cls.h_with_nick = _commit(
            cls.db, _make_person(Person.FEMALE, nick="Jinx")
        )
        register_rules(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _run(self, rule_class, rule_args):
        rule = rule_class(rule_args)
        f = GenericFilter()
        f.add_rule(rule)
        return set(f.apply(self.db)), rule

    def _assert_sql_path(self, rule, expected_in, expected_out):
        override = getattr(rule, "_db_override", None)
        self.assertIsNotNone(override, "override instance must be attached to rule")
        self.assertIsInstance(
            override.handles, frozenset, "handles must be a frozenset (SQL path taken)"
        )
        for h in expected_in:
            self.assertIn(h, override.handles)
        for h in expected_out:
            self.assertNotIn(h, override.handles)

    def test_ismale_sql_path_and_correctness(self):
        result, rule = self._run(IsMale, [])
        self.assertIn(self.h_male, result)
        self.assertNotIn(self.h_female, result)
        self._assert_sql_path(
            rule, expected_in=[self.h_male], expected_out=[self.h_female]
        )

    def test_isfemale_sql_path_and_correctness(self):
        result, rule = self._run(IsFemale, [])
        self.assertIn(self.h_female, result)
        self.assertNotIn(self.h_male, result)
        self._assert_sql_path(
            rule, expected_in=[self.h_female], expected_out=[self.h_male]
        )

    def test_disconnected_sql_path_and_correctness(self):
        result, rule = self._run(Disconnected, [])
        self.assertNotIn(self.h_connected, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_male, self.h_female, self.h_with_altname],
            expected_out=[self.h_connected],
        )

    def test_hasalternatename_sql_path_and_correctness(self):
        result, rule = self._run(HasAlternateName, [])
        self.assertIn(self.h_with_altname, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_with_altname],
            expected_out=[self.h_male, self.h_female],
        )

    def test_hasunknowngender_sql_path_and_correctness(self):
        result, rule = self._run(HasUnknownGender, [])
        self.assertIn(self.h_with_altname, result)
        self.assertIn(self.h_connected, result)
        self.assertNotIn(self.h_male, result)
        self.assertNotIn(self.h_female, result)
        self.assertNotIn(self.h_other, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_with_altname, self.h_connected],
            expected_out=[self.h_male, self.h_female, self.h_other],
        )

    def test_hasothergender_sql_path_and_correctness(self):
        result, rule = self._run(HasOtherGender, [])
        self.assertIn(self.h_other, result)
        self.assertNotIn(self.h_male, result)
        self.assertNotIn(self.h_female, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_other],
            expected_out=[self.h_male, self.h_female],
        )

    def test_nevermarried_sql_path_and_correctness(self):
        result, rule = self._run(NeverMarried, [])
        # h_male, h_female, h_with_altname have no family_list entries
        self.assertIn(self.h_male, result)
        self.assertIn(self.h_female, result)
        self.assertIn(self.h_with_altname, result)
        # h_connected and h_other and h_multi have family_list entries
        self.assertNotIn(self.h_connected, result)
        self.assertNotIn(self.h_other, result)
        self.assertNotIn(self.h_multi, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_male, self.h_female, self.h_with_altname],
            expected_out=[self.h_connected, self.h_other, self.h_multi],
        )

    def test_multiplemarriages_sql_path_and_correctness(self):
        result, rule = self._run(MultipleMarriages, [])
        self.assertIn(self.h_multi, result)
        self.assertNotIn(self.h_male, result)
        self.assertNotIn(self.h_connected, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_multi],
            expected_out=[self.h_male, self.h_connected],
        )

    def test_hasnickname_sql_path_and_correctness(self):
        result, rule = self._run(HasNickname, [])
        self.assertIn(self.h_with_nick, result)
        self.assertNotIn(self.h_male, result)
        self.assertNotIn(self.h_female, result)
        self._assert_sql_path(
            rule,
            expected_in=[self.h_with_nick],
            expected_out=[self.h_male, self.h_female],
        )

    def test_override_prepare_called_only_once(self):
        """prepare() must be called once per filter run, not once per person."""
        prepare_calls = []
        original_prepare = IsMaleOverride.prepare

        def tracking_prepare(self_override, original, db, user):
            prepare_calls.append(1)
            return original_prepare(self_override, original, db, user)

        IsMaleOverride.prepare = tracking_prepare
        try:
            rule = IsMale([])
            f = GenericFilter()
            f.add_rule(rule)
            f.apply(self.db)
        finally:
            IsMaleOverride.prepare = original_prepare

        self.assertEqual(prepare_calls, [1], "prepare() must fire exactly once")


# ---------------------------------------------------------------------------
# PrivateFilterTestsMixin
# ---------------------------------------------------------------------------


class PrivateFilterTestsMixin:
    """
    Integration tests for private/public and HasNoLatOrLon filter overrides
    across all nine Gramps object types.

    Subclasses must implement _open_db() returning an empty, open DBAPI db.
    """

    @classmethod
    def _open_db(cls):
        raise NotImplementedError

    @classmethod
    def setUpClass(cls):
        cls.db = cls._open_db()

        # Person
        priv_p = Person()
        priv_p.private = True
        cls.h_priv_person = _commit(cls.db, priv_p)
        cls.h_pub_person = _commit(cls.db, Person())

        # Family
        priv_f = Family()
        priv_f.private = True
        cls.h_priv_family = _commit(cls.db, priv_f)
        cls.h_pub_family = _commit(cls.db, Family())

        # Event
        priv_e = Event()
        priv_e.private = True
        cls.h_priv_event = _commit(cls.db, priv_e)
        cls.h_pub_event = _commit(cls.db, Event())

        # Place — private (no lat/lon), public with missing lon, public with both
        priv_pl = Place()
        priv_pl.private = True
        # lat and long default to '' so no need to set them
        cls.h_priv_place = _commit(cls.db, priv_pl)

        pl_no_lon = Place()
        pl_no_lon.lat = "12.3456"
        pl_no_lon.long = ""
        cls.h_place_no_lon = _commit(cls.db, pl_no_lon)

        pl_full = Place()
        pl_full.lat = "12.3456"
        pl_full.long = "65.4321"
        cls.h_place_full = _commit(cls.db, pl_full)

        # Citation
        priv_c = Citation()
        priv_c.private = True
        cls.h_priv_citation = _commit(cls.db, priv_c)
        cls.h_pub_citation = _commit(cls.db, Citation())

        # Source
        priv_s = Source()
        priv_s.private = True
        cls.h_priv_source = _commit(cls.db, priv_s)
        cls.h_pub_source = _commit(cls.db, Source())

        # Note
        priv_n = Note()
        priv_n.private = True
        cls.h_priv_note = _commit(cls.db, priv_n)
        cls.h_pub_note = _commit(cls.db, Note())

        # Media
        priv_m = Media()
        priv_m.private = True
        cls.h_priv_media = _commit(cls.db, priv_m)
        cls.h_pub_media = _commit(cls.db, Media())

        # Repository
        priv_r = Repository()
        priv_r.private = True
        cls.h_priv_repo = _commit(cls.db, priv_r)
        cls.h_pub_repo = _commit(cls.db, Repository())

        register_rules(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    # ------------------------------------------------------------------
    # Person private / public
    # ------------------------------------------------------------------

    def test_peopleprivate_matches_private_only(self):
        result = _apply(self.db, PeoplePrivate([]), "Person")
        self.assertIn(self.h_priv_person, result)
        self.assertNotIn(self.h_pub_person, result)

    def test_peoplepublic_matches_public_only(self):
        result = _apply(self.db, PeoplePublic([]), "Person")
        self.assertIn(self.h_pub_person, result)
        self.assertNotIn(self.h_priv_person, result)

    def test_peopleprivate_and_peoplepublic_are_disjoint(self):
        priv = _apply(self.db, PeoplePrivate([]), "Person")
        pub = _apply(self.db, PeoplePublic([]), "Person")
        self.assertEqual(priv & pub, set())

    def test_peopleprivate_and_peoplepublic_cover_all_persons(self):
        priv = _apply(self.db, PeoplePrivate([]), "Person")
        pub = _apply(self.db, PeoplePublic([]), "Person")
        total = self.db.get_number_of_people()
        self.assertEqual(len(priv) + len(pub), total)

    # ------------------------------------------------------------------
    # Family private
    # ------------------------------------------------------------------

    def test_familyprivate_matches_private_only(self):
        result = _apply(self.db, FamilyPrivate([]), "Family")
        self.assertIn(self.h_priv_family, result)
        self.assertNotIn(self.h_pub_family, result)

    # ------------------------------------------------------------------
    # Event private
    # ------------------------------------------------------------------

    def test_eventprivate_matches_private_only(self):
        result = _apply(self.db, EventPrivate([]), "Event")
        self.assertIn(self.h_priv_event, result)
        self.assertNotIn(self.h_pub_event, result)

    # ------------------------------------------------------------------
    # Place private / HasNoLatOrLon
    # ------------------------------------------------------------------

    def test_placeprivate_matches_private_only(self):
        result = _apply(self.db, PlacePrivate([]), "Place")
        self.assertIn(self.h_priv_place, result)
        self.assertNotIn(self.h_place_full, result)

    def test_hasnolatorlon_matches_places_missing_coords(self):
        result = _apply(self.db, HasNoLatOrLon([]), "Place")
        self.assertIn(self.h_priv_place, result)   # lat='' and long=''
        self.assertIn(self.h_place_no_lon, result)  # long=''
        self.assertNotIn(self.h_place_full, result)  # both present

    def test_hasnolatorlon_and_placeprivate_are_independent(self):
        # private place has no lat/lon → appears in both
        priv_result = _apply(self.db, PlacePrivate([]), "Place")
        nll_result = _apply(self.db, HasNoLatOrLon([]), "Place")
        self.assertIn(self.h_priv_place, priv_result)
        self.assertIn(self.h_priv_place, nll_result)

    # ------------------------------------------------------------------
    # Citation private
    # ------------------------------------------------------------------

    def test_citationprivate_matches_private_only(self):
        result = _apply(self.db, CitationPrivate([]), "Citation")
        self.assertIn(self.h_priv_citation, result)
        self.assertNotIn(self.h_pub_citation, result)

    # ------------------------------------------------------------------
    # Source private
    # ------------------------------------------------------------------

    def test_sourceprivate_matches_private_only(self):
        result = _apply(self.db, SourcePrivate([]), "Source")
        self.assertIn(self.h_priv_source, result)
        self.assertNotIn(self.h_pub_source, result)

    # ------------------------------------------------------------------
    # Note private
    # ------------------------------------------------------------------

    def test_noteprivate_matches_private_only(self):
        result = _apply(self.db, NotePrivate([]), "Note")
        self.assertIn(self.h_priv_note, result)
        self.assertNotIn(self.h_pub_note, result)

    # ------------------------------------------------------------------
    # Media private
    # ------------------------------------------------------------------

    def test_mediaprivate_matches_private_only(self):
        result = _apply(self.db, MediaPrivate([]), "Media")
        self.assertIn(self.h_priv_media, result)
        self.assertNotIn(self.h_pub_media, result)

    # ------------------------------------------------------------------
    # Repository private
    # ------------------------------------------------------------------

    def test_repoprivate_matches_private_only(self):
        result = _apply(self.db, RepoPrivate([]), "Repository")
        self.assertIn(self.h_priv_repo, result)
        self.assertNotIn(self.h_pub_repo, result)
