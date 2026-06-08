# FastFiltersLib — Filter Override Roadmap

This document tracks filter rules that have not yet been implemented as
SQL-accelerated overrides, with implementation notes and feasibility
assessments for each.

Already implemented overrides are **not** listed here.

---

## Tier 2 — `json_data` required, single-table SQL

These rules can be expressed as a single `SELECT handle FROM person WHERE …`
query that reads only `json_data` fields.  No JOIN to another table is needed.

### `HasNickname` — `("person", "HasNickname")`

**Original logic**

```python
def apply_to_one(self, db, person):
    return bool(person.get_nick_name())
```

`get_nick_name()` iterates `[primary_name] + alternate_names` and returns the
first non-empty `name.nick`.

**SQL approach**

```sql
-- SQLite
SELECT handle FROM person
WHERE TRIM(COALESCE(json_extract(json_data, '$.primary_name.nick'), '')) != ''

-- PostgreSQL
SELECT handle FROM person
WHERE TRIM(COALESCE((json_data::json)->'primary_name'->>'nick', '')) != ''
```

**Caveat**: This only checks `primary_name.nick`.  A person whose *only* nick
lives in an alternate name will be a false negative.  In practice this is
very rare and the SQL path can fall back to Python for those cases via a
hybrid approach (see Tier 3+ below), or the approximation can be accepted
as a documented limitation.

**Verdict**: implement as an approximation that checks `primary_name.nick`;
document the alternate-name edge case.  No fallback needed for blob-data
databases since `nick` lives inside `json_data`.

---

## Tier 3 — Single JOIN, SQL fully correct

These rules require joining the `person` table to one other table.  The SQL
can still be 100% correct and no Python post-processing is needed.

### `MissingParent` — `("person", "MissingParent")`

**Original logic**

```python
def apply_to_one(self, db, person):
    families = person.parent_family_list
    if families == []:
        return True
    for family_handle in families:
        family = db.get_family_from_handle(family_handle)
        if family:
            if not family.father_handle:
                return True
            if not family.mother_handle:
                return True
    return False
```

Matches when:
1. `parent_family_list` is empty, **or**
2. any parent family has a missing father or mother handle.

**SQL approach**

`father_handle` and `mother_handle` are secondary columns on the `family`
table.  `parent_family_list` is a JSON array in `person.json_data`.

```sql
-- SQLite (requires json_data)
SELECT p.handle
FROM   person p
WHERE  json_array_length(json_extract(p.json_data, '$.parent_family_list')) = 0
   OR  EXISTS (
         SELECT 1
         FROM   json_each(json_extract(p.json_data, '$.parent_family_list')) AS pfl
         JOIN   family f ON f.handle = pfl.value
         WHERE  f.father_handle IS NULL OR f.father_handle = ''
            OR  f.mother_handle IS NULL OR f.mother_handle = ''
       )
```

**PostgreSQL** variant would use `jsonb_array_elements_text` instead of
`json_each`.

**Fallback**: must fall back to the original for blob-data databases (no
`json_data`).

---

### `HaveChildren` — `("person", "HaveChildren")`

**Original logic**

```python
def apply_to_one(self, db, person):
    for family_handle in person.family_list:
        family = db.get_family_from_handle(family_handle)
        if family is not None and family.child_ref_list:
            return True
    return False
```

Matches persons who are a spouse in at least one family that has children.

**SQL approach**

`child_ref_list` is a JSON array in `family.json_data`.

```sql
-- SQLite (requires json_data on both tables)
SELECT p.handle
FROM   person p
WHERE  EXISTS (
         SELECT 1
         FROM   json_each(json_extract(p.json_data, '$.family_list')) AS fl
         JOIN   family f ON f.handle = fl.value
         WHERE  json_array_length(json_extract(f.json_data, '$.child_ref_list')) > 0
       )
```

**Fallback**: blob-data databases.

---

### `NoBirthdate` — `("person", "NoBirthdate")`

**Original logic**

```python
def apply_to_one(self, db, person):
    if 0 <= person.birth_ref_index < len(person.event_ref_list):
        birth_ref = person.event_ref_list[person.birth_ref_index]
        if not birth_ref:
            return True
        birth = db.get_event_from_handle(birth_ref.ref)
        if birth:
            if not birth.date or birth.date.sortval == 0:
                return True
            return False
    return True
```

Matches when there is no birth event reference, or the referenced event has
no date (sortval == 0).

**SQL approach**

`birth_ref_index` is a secondary column on `person`.  The event handle at
that index is readable from `json_data` using a dynamic array path.
`date.sortval` lives in `event.json_data`.

```sql
-- SQLite (requires json_data on person and event)
SELECT p.handle
FROM   person p
LEFT JOIN event e
       ON e.handle = json_extract(
            p.json_data,
            '$.event_ref_list[' || p.birth_ref_index || '].ref'
          )
WHERE  p.birth_ref_index < 0
   OR  p.birth_ref_index >= json_array_length(
         json_extract(p.json_data, '$.event_ref_list'))
   OR  e.handle IS NULL
   OR  json_extract(e.json_data, '$.date') IS NULL
   OR  COALESCE(json_extract(e.json_data, '$.date.sortval'), 0) = 0
```

The dynamic path `'$.event_ref_list[' || birth_ref_index || '].ref'` is
supported by SQLite's `json_extract`.  PostgreSQL needs a different approach
(e.g. `jsonb_array_element`).

**Fallback**: blob-data databases.

---

### `NoDeathdate` — `("person", "NoDeathdate")`

Identical structure to `NoBirthdate`, substituting `death_ref_index` for
`birth_ref_index`.

---

## Tier 3+ — Complex SQL or SQL + Python hybrid

These rules are harder to express cleanly in pure SQL.  A **SQL + Python
hybrid** approach can still deliver a significant speedup: SQL narrows the
candidate set (avoiding loading every object), and a small Python pass does
the final check on the reduced set.

### `HaveAltFamilies` (adopted people) — `("person", "HaveAltFamilies")`

**Original logic**

```python
def apply_to_one(self, db, person):
    for fhandle in person.parent_family_list:
        family = db.get_family_from_handle(fhandle)
        if family:
            ref = [r for r in family.child_ref_list if r.ref == person.handle]
            if ref and (ref[0].frel == ChildRefType.ADOPTED
                        or ref[0].mrel == ChildRefType.ADOPTED):
                return True
    return False
```

`ChildRefType.ADOPTED == 2`.  `frel` and `mrel` are integer fields inside
each element of `family.child_ref_list` in `json_data`.

**SQL approach**

The join chain is: `person → parent_family_list → family → child_ref_list`
(filtered by `ref == person.handle`).  Pure SQL requires nested `json_each`
and a correlated filter, which is verbose but feasible:

```sql
-- SQLite sketch
SELECT p.handle
FROM   person p
WHERE  EXISTS (
         SELECT 1
         FROM   json_each(json_extract(p.json_data, '$.parent_family_list')) AS pfl
         JOIN   family f ON f.handle = pfl.value
         JOIN   json_each(json_extract(f.json_data, '$.child_ref_list')) AS crl
         WHERE  json_extract(crl.value, '$.ref') = p.handle
           AND  (  json_extract(crl.value, '$.frel.string') = 'Adopted'
                OR json_extract(crl.value, '$.mrel.string') = 'Adopted')
       )
```

The exact JSON path for `frel`/`mrel` depends on how `ChildRefType` is
serialised (it may be stored as `{"value": 2, "string": "Adopted"}`).

**Hybrid alternative**: SQL fetches persons who have any parent families,
Python post-filters for the ADOPTED child-ref type.  Smaller win, but simpler
and certainly correct.

**Fallback**: blob-data databases.

---

### `IncompleteNames` — `("person", "IncompleteNames")`

**Original logic**

```python
def apply_to_one(self, db, person):
    for name in [person.primary_name] + person.alternate_names:
        if name.first_name.strip() == '':
            return True
        if name.surname_list:
            for surn in name.surname_list:
                if surn.surname.strip() == '':
                    return True
        else:
            return True  # no surname entries at all
    return False
```

**SQL approach**

The simplest partial SQL: catch persons whose `primary_name.first_name` is
blank (handles the majority of real-world cases):

```sql
SELECT handle FROM person
WHERE TRIM(COALESCE(json_extract(json_data, '$.primary_name.first_name'), '')) = ''
```

A complete implementation requires `json_each` over `alternate_names` and
then over each name's `surname_list`, which is a double nested `json_each` —
expensive and complex.

**Recommended approach**: SQL + Python hybrid.
- SQL pre-selects persons where `primary_name.first_name` is blank (fast,
  avoids loading most objects).
- Python re-checks the full rule (including alternate names and all surnames)
  only on the remaining candidates — expected to be a very small fraction of
  the database.

**Fallback**: blob-data databases.

---

## Tier 4 — Secondary-column comparisons and scalar json_extract, all object types

These rules read only secondary columns or a single scalar json_extract path and
compare against a parameter that is fixed at `prepare()` time.  No JOIN is needed.
Because the parameter value is known at prepare time, `selected_handles` can be
fully populated by one SQL query per rule invocation.

Many rules in this tier follow the same pattern across all nine object types
(person, family, event, place, citation, source, media, note, repository).
Each pattern is best implemented as a single base override class parameterised by
table name, with one concrete subclass per object type.

---

### `ChangedSince` — all nine object types

**Original logic**

```python
def apply_to_one(self, db, obj):
    obj_time = obj.change
    if self.since:
        if obj_time < self.since:
            return False
        if self.before:
            return obj_time < self.before
        return True
    if self.before:
        return obj_time < self.before
    return False
```

**SQL approach**

`change` is a secondary column (Unix timestamp integer) on every table.

```sql
-- "after" only
SELECT handle FROM person WHERE change >= {since}

-- "after … before"
SELECT handle FROM person WHERE change >= {since} AND change < {before}

-- "before" only
SELECT handle FROM person WHERE change < {before}
```

The correct clause is chosen in `prepare()` after parsing `self.list[0]` / `self.list[1]`.
`{since}` and `{before}` are integer literals embedded at prepare time.

**Object types**: person, family, event, place, citation, source, media, note, repository

**Verdict**: implement as a single base class `_ChangedSinceOverride(_table)`.
Fully correct, pure secondary column.

---

### `HasTag` — all nine object types

**Original logic**

```python
def prepare(self, db, user):
    tag = db.get_tag_from_name(self.list[0])
    self.tag_handle = tag.handle if tag else None

def apply_to_one(self, db, obj):
    if self.tag_handle is None:
        return False
    return self.tag_handle in obj.tag_list
```

**SQL approach**

`tag_list` in `json_data` is a JSON array of handle strings
(e.g. `["bb80c2b235b0a1b3f49"]`).  The tag handle is resolved in `prepare()`.

```sql
-- SQLite
SELECT handle FROM person
WHERE EXISTS (
    SELECT 1 FROM json_each(json_extract(json_data, '$.tag_list'))
    WHERE value = '{tag_handle}'
)

-- PostgreSQL
SELECT handle FROM person
WHERE json_data::jsonb->'tag_list' ? '{tag_handle}'
```

If the tag name does not exist, return an empty `frozenset` without querying.

**Object types**: person, family, event, place, citation, source, media, note, repository

**Verdict**: implement as `_HasTagOverride(_table)`.  Fully correct.
PostgreSQL's `?` operator makes the JSON array membership check especially clean.

---

## Tier 4a — Array-length count rules

These rules all share the same structure:

```python
def apply_to_one(self, db, obj):
    count = len(obj.<list_field>)
    if   count_type == 0: return count < N
    elif count_type == 2: return count > N
    else:                 return count == N
```

The comparison operator (`<`, `=`, `>`) and threshold `N` are both fixed at
`prepare()` time, so the WHERE clause can be written as a literal SQL condition.

```sql
-- "greater than 0"
SELECT handle FROM person
WHERE json_array_length(json_extract(json_data, '$.media_list')) > 0
```

One `_CountOverride(_table, _field, op, n)` base class suffices.

---

### `HavePhotos` / `HasGallery` — count of `media_list`

**Object types**: person, family, event, place, citation, source, media

---

### `HasNote` — count of `note_list`

**Object types**: person, family, event, place, citation, source, media

---

### `HasLDS` — count of `lds_ord_list`

**Object types**: person, family

---

### `HasAssociation` — count of `person_ref_list`

**Object types**: person

---

### `HasAddress` — count of `address_list`

**Object types**: person

---

### `HasSourceCount` / `HasSources` — count of `citation_list`

**Object types**: person, family, event, place, citation, source, media

---

### `HasRepository` (source) — count of `reporef_list`

**Object types**: source

---

## Tier 4b — Type-value equality

These rules extract a `{"value": N, ...}` type object from `json_data` and compare
the integer `value` field against a user-supplied enum constant.

---

### `HasRelType` — `("family", "HasRelType")`

**Original logic**

```python
def apply_to_one(self, db, family):
    if self.relation_type:
        if self.relation_type.is_custom() and self.use_regex:
            return self.regex[0].search(str(family.type)) is not None
        return self.relation_type == family.type
    return True
```

**SQL approach**

`family.type` lives in `json_data` as `{"_class":"FamilyRelType","value":0,"string":""}`.

```sql
-- SQLite / PostgreSQL (value known at prepare time)
SELECT handle FROM family
WHERE json_extract(json_data, '$.type.value') = {reltype_value}
```

The regex-on-custom-type path is rare; fall back to Python for that case only
by not setting `selected_handles` when `use_regex` is True.

**Verdict**: implement for the non-regex case.  Covers the vast majority of uses
(Married, Unmarried, Civil Union, Unknown).

---

### `NoteHasType` — `("note", "HasType")`

**Original logic**

```python
def apply_to_one(self, db, note):
    if self.note_type:
        return note.type == self.note_type
    return False
```

**SQL approach**

`note.type` in `json_data`: `{"_class":"NoteType","value":10,"string":""}`.

```sql
SELECT handle FROM note
WHERE json_extract(json_data, '$.type.value') = {notetype_value}
```

**Verdict**: straightforward.  Same caveat on custom-type regex as `HasRelType`.

---

### `MatchesTitleSubstringOf` — `("source", "MatchesTitleSubstringOf")`

**Original logic**

```python
def apply_to_one(self, db, source):
    return self.match_substring(0, source.title)
```

**SQL approach**

`title` is a secondary column on the `source` table.

```sql
-- SQLite (case-insensitive LIKE)
SELECT handle FROM source WHERE lower(title) LIKE lower('%{substring}%')

-- PostgreSQL
SELECT handle FROM source WHERE title ILIKE '%{substring}%'
```

For the regex variant (`use_regex=True`) use `regexp()` / `~`.

**Verdict**: trivial.  `title` is already a secondary column; no json_data needed.

---

## Tier 5 — Single JOIN or nested json_each with parameters

These rules require one JOIN or a `json_each` over a list whose elements contain
parameters-dependent sub-fields.

---

### `HasNameType` — `("person", "HasNameType")`

**Original logic**

```python
def apply_to_one(self, db, person):
    if self.name_type:
        for name in [person.primary_name] + person.alternate_names:
            if name.type == self.name_type:
                return True
    return False
```

**SQL approach**

`primary_name.type.value` is reachable with `json_extract`.
`alternate_names` is a JSON array; each element has a `.type.value` field.

```sql
-- SQLite
SELECT handle FROM person
WHERE json_extract(json_data, '$.primary_name.type.value') = {name_type_value}
   OR EXISTS (
        SELECT 1 FROM json_each(json_extract(json_data, '$.alternate_names')) AS an
        WHERE json_extract(an.value, '$.type.value') = {name_type_value}
      )
```

**Verdict**: single-table, one-level json_each.  Fully correct.

---

### `IsWitness` — `("person", "IsWitness")`

**Original logic**

```python
def apply_to_one(self, db, person):
    for event_ref in person.event_ref_list:
        if event_ref.role.value == EventRoleType.WITNESS:  # 7
            if self.event_type:
                event = db.get_event_from_handle(event_ref.ref)
                if event.type == self.event_type:
                    return True
            else:
                return True
    return False
```

**SQL approach — no event_type filter (common case)**

`event_ref_list` is a JSON array; each entry has `role.value`.

```sql
-- SQLite
SELECT handle FROM person
WHERE EXISTS (
    SELECT 1 FROM json_each(json_extract(json_data, '$.event_ref_list')) AS er
    WHERE json_extract(er.value, '$.role.value') = 7
)
```

**SQL approach — with event_type filter**

Add a JOIN to the `event` table via the `ref` field:

```sql
SELECT p.handle FROM person p
WHERE EXISTS (
    SELECT 1 FROM json_each(json_extract(p.json_data, '$.event_ref_list')) AS er
    JOIN event e ON e.handle = json_extract(er.value, '$.ref')
    WHERE json_extract(er.value, '$.role.value') = 7
      AND json_extract(e.json_data, '$.type.value') = {event_type_value}
)
```

**Verdict**: implement both cases.  When no event type is given, pure single-table.
When event type is given, one JOIN to `event`.

---

### `PersonWithIncompleteEvent` — `("person", "PersonWithIncompleteEvent")`

**Original logic**

```python
def apply_to_one(self, db, person):
    for event_ref in person.event_ref_list:
        if event_ref:
            event = db.get_event_from_handle(event_ref.ref)
            if not event.place:
                return True
            if not event.date:
                return True
    return False
```

**SQL approach**

`event.place` is a secondary column (handle string, empty when absent).
`event.date.sortval` in `json_data` is 0 when no date is set.
`event.handle` is reached via `json_extract(er.value, '$.ref')` over `event_ref_list`.

```sql
-- SQLite
SELECT p.handle FROM person p
WHERE EXISTS (
    SELECT 1 FROM json_each(json_extract(p.json_data, '$.event_ref_list')) AS er
    JOIN event e ON e.handle = json_extract(er.value, '$.ref')
    WHERE COALESCE(e.place, '') = ''
       OR COALESCE(json_extract(e.json_data, '$.date.sortval'), 0) = 0
)
```

**Verdict**: single JOIN, secondary-column check on `event.place`.  Fully correct.

---

### `SearchFatherName` / `SearchMotherName` — `("family", ...)`

**Original logic**

```python
def apply_to_one(self, db, family):
    father = db.get_person_from_handle(family.father_handle)
    if father:
        return <SearchName applied to father>
```

**SQL approach**

`father_handle` and `mother_handle` are secondary columns on `family`.
`given_name` and `surname` are secondary columns on `person`.

```sql
-- SearchFatherName: substring on given_name or surname (SQLite)
SELECT f.handle FROM family f
JOIN person p ON p.handle = f.father_handle
WHERE lower(p.given_name) LIKE lower('%{substring}%')
   OR lower(p.surname) LIKE lower('%{substring}%')
```

Same structure for `SearchMotherName` substituting `mother_handle`.

**Verdict**: one JOIN using secondary columns on both sides.  Fully correct for
the common case.  The full `SearchName` rule also checks `nick`, `title`, `famnick`,
`call` — those require `json_extract` additions to the WHERE clause.

---

### `SearchChildName` — `("family", "SearchChildName")`

**Original logic**

Iterates `family.child_ref_list` (JSON array in `json_data`), loads each child
person, then applies a name substring check.

**SQL approach**

```sql
-- SQLite
SELECT f.handle FROM family f
WHERE EXISTS (
    SELECT 1 FROM json_each(json_extract(f.json_data, '$.child_ref_list')) AS cr
    JOIN person p ON p.handle = json_extract(cr.value, '$.ref')
    WHERE lower(p.given_name) LIKE lower('%{substring}%')
       OR lower(p.surname)    LIKE lower('%{substring}%')
)
```

**Verdict**: one `json_each` + one JOIN.  Secondary-column name fields cover the
most common case; json_extract additions needed for full coverage.

---

### `SearchName` — `("person", "SearchName")`

**Original logic**

Searches `first_name`, `get_surname()`, `suffix`, `title`, `nick`, `famnick`,
`call` across primary and alternate names.

**SQL approach**

`given_name` and `surname` are secondary columns.  Additional fields require
`json_extract`.

```sql
-- Primary name fields only (fastest; secondary columns)
SELECT handle FROM person
WHERE lower(given_name) LIKE lower('%{substring}%')
   OR lower(surname)    LIKE lower('%{substring}%')
```

Full coverage (all name fields, all alternate names) requires `json_extract` on
several primary_name sub-fields and a `json_each` over `alternate_names`.  Recommended
approach: SQL pre-filters on secondary columns, Python post-checks alternate names
(same hybrid pattern as `IncompleteNames`).

**Verdict**: hybrid.  SQL covers the primary-name case fast; Python fills the gap.

---

### `InLatLonNeighborhood` — `("place", "InLatLonNeighborhood")`

**Original logic**

Checks whether `place.lat` and `place.long` fall within a bounding box computed
from centre point + radius in `prepare()`.

**SQL approach**

`lat` and `long` are secondary columns on `place`.  The bounding box (`N`, `S`,
`W`, `E`) is computed in Python during `prepare()` and embedded as literals.

```sql
SELECT handle FROM place
WHERE TRIM(COALESCE(lat,  '')) != ''
  AND TRIM(COALESCE(long, '')) != ''
  AND CAST(lat  AS REAL) BETWEEN {S} AND {N}
  AND CAST(long AS REAL) BETWEEN {W} AND {E}
```

The wrap-around (180°/−180°) case where `doublesquares=True` needs a second
OR-ed rectangle in the WHERE clause.

**Caveat**: `lat`/`long` are stored as text in Gramps.  `CAST(... AS REAL)` handles
the conversion; non-numeric values become NULL and are excluded.  The Python rule
uses `conv_lat_lon()` for normalisation — rows with unusual formats may differ.

**Verdict**: fully SQL-feasible.  Approximation risk only for non-standard lat/lon
string formats.

---

## Tier 5+ — Complex or not feasible

These rules cannot be expressed efficiently in SQL, require Python logic that has
no SQL analogue, or involve recursive graph traversal.

| Rule | Reason not feasible |
|---|---|
| `HasBirth` / `HasDeath` | Multi-field event match: date range, place hierarchy display, description substring — requires Python `Date.match()` and `place_displayer.display()` |
| `HasEvent` (person) | Same as HasBirth/HasDeath but for arbitrary event types |
| `HasFamilyEvent` | Three-table chain: person → family → event; adds place display |
| `FamilyWithIncompleteEvent` | Three-table chain: person → family → event; six loads per person |
| `HasCitation` | Multi-field citation match: page substring, date range, confidence level |
| `HasAttribute` | Attribute type + value substring across json_each; type comparison is enum-vs-string; many attribute types |
| `HasFamilyAttribute` | Same as HasAttribute but on the family JOIN chain |
| `HasNameOf` | Eleven optional substring fields across primary + alternate names and surname_list; too many combinations |
| `HasNameOriginType` | Double nested json_each: alternate_names → surname_list → origintype |
| `RegexpName` | Regexp across seven name fields × (1 + N alternate names); expensive even in SQL |
| `HasTwins` | Requires grouping children's birth event sortvals — aggregation across a JOIN chain |
| `HasTitle` (place) | Uses `place_displayer.display()` which traverses the place hierarchy; no SQL equivalent |
| `HasPlace` (place) | Uses `get_locations()` recursive place hierarchy traversal |
| `IsEnclosedBy` (place) | Recursive closure (`located_in()`); would need a recursive CTE over the `enclosed_by` column — possible but complex; low value |
| `WithinArea` (place) | Requires `hypot()` (Euclidean distance) — SQL has no built-in, would need `sqrt((lat-clat)^2 + (lon-clon)^2)` which is fragile for text-stored coordinates |

---

## Summary table

| Rule | Tier | Object types | Join target | Notes |
|---|---|---|---|---|
| `HasNickname` | 2 | person | — | Approximate: primary name only |
| `MissingParent` | 3 | person | family | Fully correct |
| `HaveChildren` | 3 | person | family | Fully correct |
| `NoBirthdate` | 3 | person | event | Dynamic array index path |
| `NoDeathdate` | 3 | person | event | Same as NoBirthdate |
| `HaveAltFamilies` | 3+ | person | family | Nested json_each |
| `IncompleteNames` | 3+ | person | — | Hybrid: SQL + Python alternate names |
| `ChangedSince` | 4 | all 9 | — | `change` secondary column |
| `HasTag` | 4 | all 9 | — | json_each / PG `?` operator on tag_list |
| `HavePhotos`/`HasGallery` | 4a | person, family, event, place, citation, source, media | — | json_array_length on media_list |
| `HasNote` | 4a | person, family, event, place, citation, source, media | — | json_array_length on note_list |
| `HasLDS` | 4a | person, family | — | json_array_length on lds_ord_list |
| `HasAssociation` | 4a | person | — | json_array_length on person_ref_list |
| `HasAddress` | 4a | person | — | json_array_length on address_list |
| `HasSourceCount` | 4a | person, family, event, place, citation, source, media | — | json_array_length on citation_list |
| `HasRepository` | 4a | source | — | json_array_length on reporef_list |
| `HasRelType` | 4b | family | — | json_extract type.value; no regex |
| `NoteHasType` | 4b | note | — | json_extract type.value |
| `MatchesTitleSubstringOf` | 4b | source | — | `title` secondary column |
| `HasNameType` | 5 | person | — | json_extract + json_each alternates |
| `IsWitness` | 5 | person | event (optional) | json_each event_ref_list, role.value=7 |
| `PersonWithIncompleteEvent` | 5 | person | event | place secondary col + date.sortval |
| `SearchFatherName` / `SearchMotherName` | 5 | family | person | secondary-column JOIN |
| `SearchChildName` | 5 | family | person | json_each child_ref_list + JOIN |
| `SearchName` | 5 | person | — | Hybrid: secondary cols + Python alternates |
| `InLatLonNeighborhood` | 5 | place | — | CAST lat/long, BETWEEN bounds |

## Implementation order

1. `HasNickname` — easiest; single table; document the approximation.
2. `MissingParent` — high value; family secondary columns make the JOIN clean.
3. `HaveChildren` — common filter; same JOIN pattern as MissingParent.
4. `NoBirthdate` / `NoDeathdate` — dynamic array index; worth verifying
   SQLite and PostgreSQL both support it before committing.
5. `HaveAltFamilies` — assess whether pure SQL or hybrid is cleaner.
6. `IncompleteNames` — hybrid approach recommended; pure SQL is impractical.
7. `ChangedSince` — high value, all 9 types, pure secondary column; one base class.
8. `HasTag` — high value, all 9 types, one base class.
9. Tier 4a count rules — all share one base class; implement all at once.
10. `HasRelType`, `NoteHasType`, `MatchesTitleSubstringOf` — trivial type/column comparisons.
11. `HasNameType`, `IsWitness` — single json_each, high value.
12. `PersonWithIncompleteEvent` — one JOIN, secondary-column check.
13. `SearchFatherName` / `SearchMotherName` / `SearchChildName` — secondary-column JOINs.
14. `SearchName` — hybrid; implement after SearchFatherName for consistency.
15. `InLatLonNeighborhood` — last; geospatial; requires float-cast caveat.
