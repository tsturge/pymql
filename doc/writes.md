# Writes

A write is resolved like a read, lowered to "low JSON" - the graph
shape of the change - then turned into `QueryPrimitive`s that first
read what already exists and then write what doesn't. The examples
write to a freshly bootstrapped graph as `/user/root`, privileged. As
`/user/metaweb`, they need no privilege (see [MQL on
graphd](graph-model.md#permissions-and-scope)).

## The example

```json
{"create": "unless_exists", "type": "/type/namespace", "name": "Sprockets",
 "guid": null}
```

The first time, after the schema and ids are cached, the graphd
traffic is a lookup and then a write, which creates the node with its
three links in one request:

```
read (... (<-left typeguid=<type/object/type> right=<type/namespace> ...)
          (<-left typeguid=<type/object/name> value="Sprockets" right=<lang/en> ...) ...)
  -> []

write cost="tu=30" dateline="" id="graph_write;..."
(scope=<root user> left=null right=null
  (<-left scope=<root user> typeguid=<type/object/type> right=<type/namespace>)
  (<-left scope=<root user> typeguid=<type/object/name> datatype=string
          value="Sprockets" right=<lang/en>)
  (<-left scope=<root user> typeguid=<has_permission> right=<boot/all_permission>))
  -> [<new node>, [<type link>], [<name link>], [<permission link>]]
```

```json
{"create": "created", "type": "/type/namespace", "name": "Sprockets",
 "guid": "#0701a8c040007d9c800000000000055a"}
```

The second time, the lookup finds the node, nothing is written, and
the result says `"create": "existed"`.

Giving it a key:

```json
{"guid": null, "type": "/type/namespace", "name": "Sprockets",
 "key": {"connect": "insert", "value": "sprockets", "namespace": "/"}}
```

finds the object, then writes one link, from the root namespace to it,
and asks graphd to refuse it if the namespace already has the key:

```
write (left=<root namespace> right=<Sprockets> typeguid=<has_key>
       datatype=string comparator="octet" value="sprockets"
       scope=<root user> unique=(left typeguid value datatype))
```

The result says `"connect": "inserted"`; run again, `"present"`, with
no write. `{"id": "/sprockets", "name": null}` now finds it.

## Low JSON

`HighQuery.build_low_json_root()` turns the resolved query into low
JSON: the same tree, keyed by property, with the schema compiled away.
`@` keys describe a node; `:` keys describe the link that reaches it
from the clause above. The key example lowers to:

```json
{
 "@guid": null,
 "type": {":typeguid": "<type/object/type>", ":reverse": false,
          "@guid": "<type/namespace>"},
 "name": {":typeguid": "<type/object/name>", ":reverse": false,
          ":unique": "value", ":datatype": "string", ":value": "Sprockets",
          "@guid": "<lang/en>"},
 "key":  {":typeguid": "<has_key>", ":reverse": true, ":datatype": "string",
          ":value": "sprockets", ":unique": "key", ":comparator": "octet",
          "@guid": "<root namespace>", ":link": true}
}
```

- `:reverse: true` means the object is the link's `right`, as for a
  key (the namespace is its `left`).
- `:unique` says what must be unique, which becomes graphd's
  `unique=`.
- The directives have become flags:
  - `"create": "unless_exists"` becomes `"@ensure": true`, and
    `"unconditional"` becomes `"@insert"`;
  - `"connect": "insert"` becomes `":link": true`, and `"delete"`
    becomes `":unlink"`;
  - `"update"` becomes `":update": "right"` or `"left"`, the end that
    changes.

Low JSON is also an interface in its own right: `LowQuery.read()` and
`write()` (`mql/lojson.py`) take it directly, as the bootstrap does.

## The stages

`HighQuery.write_or_check()` (`mql/hijson.py`):

1. `resolve_schema()`, as for a read, in `WriteMode`. Writes are
   stricter: no `/type/link`, no reflection or extension properties,
   `create` only on objects, `connect` only below the root, `update`
   only on unique properties.
2. `build_low_json_root()` builds the low JSON.
3. `LowQuery.internal_write_or_check()` (`mql/lojson.py`) does the
   work:
   - `make_orig()`, `make_parents()`: the same clause objects as reads.
   - `scope.check_write_defaults()`: a `$user`; `$permission`, which
     the user must be allowed to write under (or be privileged);
     `$authority` and `$attribution`.
   - `add_implied_writes()`: propagates `@insert`/`@delete` to the
     links that must come with them, and adds the new node's
     `+has_permission` link.
   - `add_query_primitives()`: a `QueryPrimitive` (`mql/qprim.py`) per
     node and per link, each with a state: `match`, `insert`, `ensure`,
     `ensurechild`, `link`, `unlink`, `delete`, `update`.
   - `link_query_primitives_root()`: wires them into a tree, with
     unique and ordering checks added as extra primitives.
   - `dispatch_prepares()`: the reads. Every primitive that isn't an
     unconditional insert is looked for: does the object exist (for
     `match` and `ensure`)? Is the link already there (for `link`)?
     What is the current value (for `update`)? Each answer moves its
     primitive to a final state: an `ensure` that found its object
     becomes a match; a `link` that is present needs no write; a
     `match` that found nothing is an error.
   - `check_circularity()`: the query mustn't change one thing in two
     places.
   - `check_write_access()`: every new node gets `$permission`; every
     new link needs write permission on its `left`'s permission; keys
     need permission on the namespace; and so on.
   - `generate_write_queries()`: for each clause whose node or link
     must be created, removed or changed, one graphd `write` of that
     primitive and the new ones nested under it, with `unique=` clauses
     where the schema requires them and `scope=<user>` on everything.
     graphd returns the new guids, which are attached to the
     primitives (`attach_write_results()`).
   - `generate_write_result()`: low JSON again, filled in, with what
     happened to each part.
4. `lookup_all_ids()` and `create_high_result()`: back to MQL - guids to
   ids, flags to `created`, `existed`, `connected`, `inserted`,
   `present`, `deleted`, `absent`, `updated`
   (`create_write_directive_result()`).
5. `write_dateline` is exported: the dateline of graphd after the
   write. A client passes it to its next reads (as the `dateline=`
   modifier) to be sure of seeing its own write.

## Check mode

`HighQuery.check()` runs the same stages in `CheckMode`: every read,
every permission check, but `generate_check_responses()` instead of the
writes. It answers what a write would do - `"create": "created"`,
`"connect": "present"` - with `false` for guids that would be new.

## Atomicity

A write is several graphd requests: the reads, then one or more
writes. graphd makes each `write` request atomic, and `unique=` makes
graphd itself refuse a duplicate key or unique value, even if another
writer got in between MQL's read and its write.
`generate_write_queries()` handles graphd's refusal (`EXISTS` or
`OUTDATED`) in three ways:

- a key someone else just created is the same key: success;
- on the first write of the request: nothing was written, so it
  raises "Uniqueness check failed (probably this write has already been
  done)";
- after an earlier write of the same request: there is no transaction
  to roll back, so it logs a fatal error and raises "Write partially
  complete".
