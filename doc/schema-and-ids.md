# Schema, ids and caches

Two things make MQL more than a translation of JSON into graphd: the
schema, which says what a key means, and ids, which name objects by
path. Both are read from the graph and cached in the process.

## Loading the schema

`SchemaFactory` (`mql/schema.py`), made once per `HighQuery`, holds
the schema:

- When it starts, it loads the whole `/type` domain - every core type
  and its properties - in one read (`SchemaDomain.load_from_graph()`,
  with the low-JSON query `get_domain_query()`).
- Any other type is loaded the first time a query names it, by id or
  guid: one read of the type, its properties, their expected types,
  `unique` flags, master and reverse properties, delegation and
  enumerations (`SchemaType.load_from_graph()`, `get_schema_query()`).

A loaded type is a `SchemaType`, with a category: `object`, `value`
(`/type/value` and the types under it), `link` (`/type/link`) or
`reflect` (`/type/reflect`). A clause's category must match its
property's expected type's: no objects where values belong.

Each property is a `SchemaProperty`, with the guid its links use as
`typeguid`:

- a forward property's links have its own guid as their type;
- a reverse property (one with a `master_property`) is the master's
  links read the other way: its `typeguid` is the master's, and
  `reverse` is set;
- a delegated property uses the links of the property it delegates
  to;
- `!/a/b/c`, written in a query, is the same property reversed
  (`get_reversed()`).

`unique`, `master_unique` and `reverse_unique` say whether one value
is allowed at each end. Reads use them to check `null` against the
graph's answer; writes use them to allow `update` and add graphd
`unique=` clauses.

## Resolving a key

`HighQuery.resolve_property()` (`mql/hijson.py`), given a clause's type:

1. `link` is the link the clause came through (`/type/link`).
2. A full id, `/t/x/p` or `!/t/x/p`, loads `/t/x` if need be and takes
   its property `p`, reversed for `!`.
3. A short name, `p`, is looked up with `SchemaType.getprop()`:
   - first among `/type/object`'s (or `/type/value`'s) properties;
   - then the type's own;
   - then those of the types it extends, where a name found in two
     extended types is an error.
4. Anything else is an error. A short name can't be reversed, and a
   reserved word can't be a prefix.

## When the schema changes

Nothing tells a running MQL that the schema changed. If resolving a
query raises `MQLTypeError` - a type or property not found -
`HighQuery.resolve_schema()` flushes the id cache and the schema
(`SchemaFactory.flush()`) and tries once more, so a type or property
added since it was cached is found. A change that doesn't cause that
error isn't noticed until something does: an expected type changed, or
a property made unique.

## Ids to guids

`NamespaceFactory` (`mql/lookup.py`) and `NameMap`
(`mql/namespace.py`) resolve ids:

- A **guid** (`#...`) is itself.
- A **mid** (`/m/...`) is decoded to a guid arithmetically
  (`mql/mid.py`). Then `lookup_guids_of_mids()` reads whether that
  object has a `replaced_by` link - it was merged into another - and
  if so uses the replacement. These lookups aren't cached.
- A **path** is resolved key by key from the root namespace.
  `NameMap.lookup_multiple()` builds one graphd read for all the ids a
  query needs, sharing their common prefixes. It reads only the parts
  it doesn't already know: each `Namespace` it has seen caches its
  keys.

During a query, `LookupManager` (`mql/env.py`) collects the ids as
`DeferredGuidLookup` placeholders and resolves them together, in at
most two round trips (mids, then paths).

## Guids to ids

The other way, for results, `lookup_ids()`:

1. Cached guids are answered from `self.guids`.
2. The rest are read together: each object's `has_key` links
   backwards, and their namespaces' keys, three levels up, plus the
   object's type and its `/freebase/object_hints/best_hrid` if it has
   one (`lookup_id_query()`).
3. `search_id_result()` picks one id:
   - the `best_hrid`, if present;
   - else the shortest path;
   - except that any three-level path beats a `/boot` one;
   - between paths of the same length, any one.
4. With no keyed path, the id is the object's mid, which needs a known
   graph id (see [The language](language.md#ids-guids-and-mids)).

## What is cached, and for how long

| Cache | Where | Lifetime |
|---|---|---|
| Schema: domains, types, properties | `SchemaFactory` | The process; flushed on an `MQLTypeError` |
| Namespace keys, id to guid | `NameMap`'s `Namespace` objects | The process; flushed with the schema |
| Guid to id | `NamespaceFactory.guids` | The process; flushed with the schema |
| Permission checks | `varenv['write_permission']` | One request |

Reads with `as_of_time` bypass the guid-to-id cache: ids may have been
different then.

Within one process, MQL assumes the schema and namespaces change only
through it. A long-running server sharing a graph with other writers
should expect stale ids and schema until a flush. Callers that cache
`MQLService` objects, as the mql-browser does, drop them when graphd's
dateline moves.
