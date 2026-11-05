# MQL on graphd

graphd stores primitives. Each has a guid, and optionally a `left`, a
`right`, a `typeguid` and a `scope` (all guids of other primitives), a
`value` with a `datatype`, a `timestamp`, a `live` flag, and versions
(`previous`/`next`). graphd has no idea what a type, a name or an id
is: MQL builds all of that out of primitives, by conventions.

## Objects and links

- An **object** is a primitive with no `left` or `right`: a node. In
  graphd queries MQL writes it as `left=null right=null`.
- A **property value that is an object** is a link: a primitive with
  `left` = the object that has the property, `right` = its value, and
  `typeguid` = the property's guid. `/fbe/film/directed_by` from *42* to
  Brian Helgeland is a link `left=<42> right=<Helgeland>
  typeguid=<directed_by>`.
- A **reverse property** (`!/fbe/film/directed_by`) is the same link
  read from the other end: from the `right`, find links of that type
  and step to their `left`.
- A **value** is a link with a `value` and no `right` (`typeguid=<the
  property>`, `value="2013-04-12"`, `datatype=timestamp`), or - for
  text, which has a language - with `right` = the language object
  (`/lang/en`).

## The core properties

| MQL | Stored as |
|---|---|
| `name` | value links of type `/type/object/name`, `right` = the language |
| `type` | links of type `/type/object/type` (graphd's `is_instance_of`) to each type |
| `key` | links of type `has_key` from a namespace to the object, `value` = the key |
| `permission` | a link of type `has_permission` (`/boot/has_permission`) to a permission object |
| `creator`, attribution | the link's or node's `scope`: the user who wrote it |
| `timestamp` | graphd's own timestamp on the primitive |

So the clause `"type": "/fbe/film"` becomes, in graphd:

```
(<-left typeguid=<type/object/type> right=<fbe/film> value=null pagesize=1 result=(()))
```

"a link whose left is this node, of type `is_instance_of`, pointing at
`/fbe/film`" - required, returning nothing (`result=(())`).

## Namespaces and ids

An id is a path of keys. A **namespace** is an object with `has_key`
links to its children: `left` = the namespace, `right` = the child,
`value` = the key, `typeguid` = `has_key`. `/fbe/film` is: from the
root namespace, the `has_key` link with value `fbe`, to the `/fbe`
domain; from there, the one with value `film`, to the type.

To resolve an id, MQL reads that chain from the root in one graphd
request. Resolving `/fbe/film_director`:

```
read (guid=<root namespace> result=(guid contents)
  (<-left optional typeguid=<has_key> comparator="octet" value="fbe" result=contents
     right->(result=(guid contents)
       (<-left optional typeguid=<has_key> comparator="octet" value="film_director"
          result=(right)))))
```

reply: `[<root>, [<fbe>, [<fbe/film_director>]]]`.

Going the other way - guid to id - reads a node's `has_key` links
backwards (`<-right typeguid=<has_key>`), and their namespaces' keys,
and so on, up to three levels, and picks the best path (see [Schema,
ids and caches](schema-and-ids.md)).

Keys are unique within a namespace: when MQL writes one it asks graphd
to enforce it, with `unique=(left typeguid value datatype)` on the
write.

## Finding the root

The guids of the root namespace, `has_key` and the root user differ
from graph to graph. graphd primitives can have a `name`, distinct from
MQL's `name` property, and bootstrapping gives these three the graphd
names `ROOT_NAMESPACE`, `HAS_KEY` and `ROOT_USER`. When a `LowQuery` is
made, `BootNamespace` (`mql/namespace.py`) finds them with one graphd
read by those names, which also reads the keys of `/boot`, `/type` and
`/lang`. Everything else is found from there, by key.

`/boot` holds the guids MQL itself needs by name: `has_permission`,
`is_instance_of`, `root_user`, `all_permission`, and so on
(`LowQuery.lookup_boot_guid()`).

## Types and properties as data

The schema is in the graph too:

- a type is an object of type `/type/type`, in a domain's namespace;
- its properties are objects of type `/type/property`, as keys of the
  type: `/fbe/film/directed_by` is the key `directed_by` in the
  namespace `/fbe/film`;
- a property's `expected_type`, `unique`, `master_property` (for a
  reverse property), `delegated` and `enumeration` are properties of
  it, like any other.

A property's guid is the `typeguid` of its links. MQL loads a type's
schema with one large graphd read, and caches it (see [Schema, ids and
caches](schema-and-ids.md)).

## Permissions and scope

Every object has a permission (`/type/object/permission`); a
permission permits user groups; users are members of groups. Before a
write, `scope.check_write_defaults()` (`mql/scope.py`) requires a
`$user`, and reads the permission's groups and their members to check
that the user may write under `$permission`. That defaults to
`/boot/all_permission` (`Varenv`, `mql/env.py`). The check is skipped
when the environment is privileged: `privileged` set to the Python
object `scope.Privileged`, as a loader writing as `/user/root` does. (In
a freshly bootstrapped graph, `/user/metaweb` is in a group that
`/boot/all_permission` permits, and `/user/root` isn't: an
unprivileged write as root fails with "User /user/root cannot create
with permission ...".) `$authority`
lets a user write with another's rights, with `scope.Authority`.

A new object gets a `has_permission` link to `$permission`. A link has
no permission of its own: it is governed by its `left`'s, so writing
one needs the user to have that permission.

Every primitive MQL writes has `scope=<user>`: graphd records who
wrote it, and MQL reads that back as `creator` and attribution.

## Bootstrapping

An empty graphd holds none of this. `bootstrap/bootstrap.py` loads
`bootstrap/otg.bootstrap`: the root namespace, `has_key`, the root
user, `/boot`, `/type` with its core types and properties, `/lang`,
`/user` and the permission objects - written with the graphd names
above. A graph loaded that way is ready for MQL; data then goes in by
MQL writes, or, much faster, by writing primitives that follow the
same conventions directly (as the dblp loader does).
