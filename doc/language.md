# The language

The parts of MQL that the rest of these pages rely on. The MQL manual
has the rest.

## Query by example

A query is JSON shaped like the answer. Given values constrain the
match; `null`, `[]` and `{}` ask for values to be filled in:

```json
{
  "id": "/en/42_$0028Biographical_Film$0029",
  "type": "/fbe/film",
  "name": null,
  "directed_by": [{"id": null, "name": null}],
  "initial_release_date": null,
  "genre": []
}
```

```json
{
  "id": "/en/42_$0028Biographical_Film$0029",
  "type": "/fbe/film",
  "name": "42",
  "directed_by": [{"id": "/en/Brian_Helgeland", "name": "Brian Helgeland"}],
  "initial_release_date": "2013-04-12",
  "genre": ["Biographical film", "Drama", "Sports films"]
}
```

- `null` asks for one value: an error if there are several, `null` if
  there are none.
- `[]` asks for all of them: a list, empty if there are none. For an
  object-valued property the list holds names; for a value property,
  the values.
- `{}` and `[{}]` are subqueries: they return the object's (or the
  objects') default fields, or exactly the fields written inside.
- A subquery written as an object or list of objects constrains the
  match: the object above matches only if the subquery matches
  something (unless it says `"optional": true`). A bare `null` or `[]`
  doesn't.
- The top of a query is an object (at most one match, or an error) or a
  list of one object (all the matches, 100 at a time by default).

In the code, `HighQuery.make_orig()` (`mql/hijson.py`) classifies every
clause by its "terminal": `N` for `null`, `L` for `[]`, `D` for `{}`,
`V` for a given value, and none for a subquery with keys of its own.

## Ids, guids and mids

- A **guid** names one graphd primitive: `#` and 32 hex digits, such as
  `#0100007f4000349d8000000000009f03`. Every object has exactly one.
- An **id** is a path of keys from the root namespace: `/fbe/film`,
  `/en/Brian_Helgeland`. An object can have several ids, or none.
  Characters outside `[A-Za-z0-9_-]` in a key are written `$XXXX`
  (hex), so `42 (Biographical Film)` is `42_$0028Biographical_Film$0029`.
- A **mid** is a short machine id, `/m/0abc12`, computed from the guid
  (`mql/mid.py`). Encoding one depends on knowing the graph's id, which
  is part of every guid; `mid.py` knows only Freebase's, so in another
  graph an object with no key has no id MQL can print, and asking for
  `"id"` of one fails with `UnknownGraphID`. Ask for `"guid"` instead.

`"id"` in a query takes any of these; in a result it is the object's
best id (see [Schema, ids and caches](schema-and-ids.md)).

## Types and properties

Every object is an instance of `/type/object` and of any number of
other types, listed by its `type` property. A type is a set of
properties, each with an expected type: `/fbe/film/directed_by` expects
`/fbe/film_director`, `/fbe/film/initial_release_date` expects
`/type/datetime`.

A key in a query names a property:

- **A full property id**, `/fbe/film/directed_by`, works anywhere.
- **A short name**, `directed_by`, is looked up on the clause's type:
  the `type` given in the clause, or else the property's expected type
  (so inside `"directed_by": [{...}]`, short names are looked up on
  `/fbe/film_director`). With neither, the clause is a `/type/object`,
  and only its properties (`id`, `guid`, `name`, `type`, `key`, `mid`,
  `timestamp`, `creator`, `permission`...) have short names. That's why
  `{"id": ..., "directed_by": []}` fails with "Type /type/object does
  not have property directed_by".
- **A reverse property**, `!/fbe/film/directed_by`, follows a property
  backwards: from a director to the films with it. It must be a full
  id.
- **A prefix**, `a:name`, `b:name`, lets one clause use the same
  property twice, with different constraints.

Every type is either an object type or a value type (`/type/text`,
`/type/int`, `/type/float`, `/type/boolean`, `/type/datetime`,
`/type/rawstring`, `/type/uri`, `/type/key`...), plus two special
categories: `/type/link`, which describes a link itself, and
`/type/reflect`, whose properties (`any_master`, `any_reverse`,
`any_value`) match any property.

## Values

A value property returns the value: a string, number, boolean or
datetime string. As a subquery it has its own fields:
`{"value": null, "lang": null}` for text, `{"value": null, "type":
null}` for any value.

Text is stored per language: `name` returns the English name
(`/lang/en`) unless the environment's `lang` says otherwise.

## Directives

Keys that aren't properties (`HighQuery.read_directives`):

| Directive | Meaning |
|---|---|
| `"limit": N` | At most N results (default 100); `0` for none, with `count` |
| `"sort": "name"` / `"-name"` / `["a", "b.c"]` | Order a list by keys of its clause, or of unique subqueries (`b.c`) |
| `"optional": true` | The clause need not match (also `"optional"`; `false` or `"required"` is the default); `"forbidden"` means it must not match |
| `"count": null` | Add the number of matches beside the results |
| `"estimate-count": null` | The same, estimated: cheaper on large sets |
| `"return": "count"` | Return the number instead of the results |
| `"return": "key"` | Return that key's value instead of the clause |
| `"return": ["a", "b"]` | Return an array of those keys' values |
| `"return": {"x": "a"}` | Return an object of them, renamed |
| `"macro": "m"` | Merge in the keys of the clause `m` from the environment's `macro` dictionary (reads only) |
| `"reach": {...}` | The objects reachable from this one by shortest paths (reads only; below) |

`return` keys can be dotted paths, `"film.name"`, into unique
subqueries.

`reach` searches for shortest paths, with graphd's `<-path`. Its keys
are a subquery on the objects reached, plus `step` (the property to
follow, `"!P"` backwards, `step|=` for several, or a subquery with
`"*"` marking the next object), `steps` (the distance, or `"steps<=":
N`), `path` and `paths`:

```json
{"id": "/en/test/alice",
 "reach": {"step": "/en/test/person/knows", "id": "/en/test/frank",
           "steps": null, "path": [{"name": null}]}}
```

```json
{"id": "/en/test/alice",
 "reach": {"id": "/en/test/frank", "steps": 3,
           "path": [{"name": "Alice"}, {"name": "Bob"}, {"name": "Dave"},
                    {"name": "Frank"}]}}
```

See [the path search proposal](path-proposal.md), alternative A. Writes add `create` and `connect` (below). `"index": null`
looks like a directive but is a result key: the position of a link in
an ordered property.

Options that apply to the whole query come from the environment, not
the query: `cursor`, `as_of_time`, `lang`, `user`, `permission`,
`deadline`, `debug_token`, and so on (`MQLService.read()` and
`write()` in `__init__.py`).

## Comparisons

A key ending in an operator compares rather than matches:

- `"value<"`, `"<="`, `">"`, `">="`: order comparisons on values,
  `timestamp`, and (as `"newest>"`...) history;
- `"name~=": "*Helgeland*"`: a pattern match on words;
- `"type|=": ["/fbe/film", "/fbe/tv_program"]`: any one of a list;
- `"genre!=": "Drama"`: not equal.

They go on any property key: `"initial_release_date>=": "2010"`.

## Links

`/type/link` is the type of a link itself. `"link": {...}` inside a
property clause describes the link that property traversed (its
`timestamp`, `creator`, `master_property`, `operation`...), and a query
whose root is `{"type": "/type/link", ...}` matches links directly.
Link queries are reads only.

## History

- `as_of_time` (environment) reads the graph as it was at a time or
  after a given primitive; graphd's `asof`.
- `/type/link` queries with `"valid": false` and `"operation"` see
  links that have been replaced or deleted.

## Writes

A write is a query with directives saying what to change. Two
directives do it:

- `"create"` on an object clause:
  - `"unconditional"` makes a new object every time;
  - `"unless_exists"` makes one unless an object matching the clause
    already exists, and then returns that one;
  - `"unless_connected"` makes one unless one is already connected
    where the clause says.
- `"connect"` on a property clause:
  - `"insert"` adds the link (nothing changes if it is there);
  - `"delete"` removes it;
  - `"update"` replaces the value of a unique property (an error on one
    that isn't unique);
  - `"replace"` does the same on a unique property, and inserts on one
    that isn't.

The result is the query, filled in, with each directive replaced by
what happened: `created`, `existed`, `connected`, `inserted`,
`present`, `deleted`, `absent`, `updated`. See [Writes](writes.md).

## Errors

Errors are `MQLError` subclasses (`mql/error.py`): `MQLParseError` (the
query is malformed), `MQLTypeError` (a type or property doesn't exist,
or doesn't fit), `MQLResultError` (the graph's answer doesn't fit the
query: two values for a `null`, for instance, as
`MQLTooManyValuesForUniqueQuery`), `MQLAccessError` (no permission),
`MQLValueAlreadyInUseError`, `MQLInternalError`. Each records the
clause of the query where it happened.
