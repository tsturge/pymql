# Path search in MQL: a proposal

Status: a proposal. Alternative B is implemented on the `reach-b` branch
(see [B as implemented](#b-as-implemented), at the end). It builds on
graphd's `<-path` constraint (graphd's `doc/path-proposal.md`), which is
implemented: MQL compiles to it, and graphd needs nothing new to answer
correctly (but see [Speed](#speed)). All searching and filtering happens
in graphd; pymql only writes the query and shapes the reply.

There are two alternatives. They share the directive, the targets and
the rules (below), and differ in how a step names the next object and
in the shape of the result:

- **A**: a step marks the next object with `"*"`; a path comes back
  as an array of nodes, with `via` for what each step passed through.
- **B**: a step is plain MQL nesting, and its innermost object is the
  next object; a path comes back nested, as the step written out once
  per step.

Open questions are at the end.

## Why

graphd can find shortest paths: from an object, by a step - a pattern
from one object to the next - to the nearest objects that match a
constraint, or a named one. MQL can't ask for them, so the one client
that wants them, the mql-browser's path view, sends graphd queries
directly, around MQL and its schema. With MQL syntax, clients write
steps as properties, targets as ordinary subqueries, and get answers in
MQL's terms (ids, names, types).

## Common to both

### The directive

A new read directive, `"reach"`, holds a subquery for the objects
reachable from the object around it:

```json
{
  "id": "/en/michael_stonebraker",
  "reach": {
    "step|=": ["/dblp/publication/author", "!/dblp/publication/author"],
    "id": "/en/donald_knuth",
    "name": null,
    "steps": null
  }
}
```

Inside `reach`, a few keys are reserved - `step`, `steps`, `path` and
`paths`, and in A also `via` in a path's nodes. Everything else is an
ordinary MQL subquery on the target: `id`, `name`, `type`, any
property, nested subqueries. They pick which objects match, and their
`null`s return values, as anywhere in MQL.

| MQL | graphd |
|---|---|
| `"reach": {...}` | `(<-path ...)` |
| `step` | `step=(...)` |
| `"steps<=": 6` | `steps<=6` |
| the target's constraints | the `<-path` constraint's own |
| `"steps": null` | the `steps` result atom |
| `"path"` | the `path` and `via` result atoms |
| `"paths"` with `limit` | a list of paths, with `pathlimit` |
| `"paths": {"return": "count"}` | `path-count` |

### Simple steps

- **One property.** `"step": "/people/person/parents"` follows the
  link forward; `"step": "!/people/person/parents"` follows it
  backward.
- **Alternatives.** MQL's `|=` takes any one of several:
  `"step|=": ["/dblp/publication/author", "!/dblp/publication/author"]`
  goes either way along author links. With the reflection properties,
  `"step|=": ["/type/reflect/any_master", "/type/reflect/any_reverse"]`
  is any link, either way - the browser's path view without "via".

Each alternative of `step|=` can also be a full step, written as A or
B writes one.

### How alternatives compile

A link is a primitive with `left`, `right` and the property as its
type: "X has property P whose value is Y" is a link from X to Y. So,
from the current object X:

- forward, `"P"`: links whose left is X; the next object is the link's
  right - `(<-left typeguid=P right->(*))`;
- backward, `"!P"`: links whose right is X; the next object is the
  link's left - `(<-right typeguid=P left->(*))`.

That is how pymql already compiles `!` (`add_query_primitive_link`,
`build_low_json`). A `|=` list becomes a graphd "or" inside the step,
each alternative with its own direction:

```
step=(result=(contents)
       {(<-left  typeguid=P result=((name)) right->(*))} |
       {(<-right typeguid=P result=((name)) left->(*))})
```

graphd walks the alternatives as a union, and follows an "or" whose
branches are each a chain through its chain walk, from one end or both:
on dblp, either way along author links from Stonebraker to Knuth takes
0.07 s warm, 2.8 s cold. `via` reports the first alternative that
matches, so MQL can return it under that alternative's own key
(`"/dblp/publication/author"` or `"!/dblp/publication/author"`), and a
client can tell which way each step went.

### Distance

`"steps": null` returns the distance; `"steps<=": 6` (or `<`, `>`,
`>=`), or `"steps": 3`, constrains it. As in graphd, that is the
shortest distance.

### One match or many

The usual MQL rules:

- `"reach": {...}` expects at most one match; more is MQL's "unique
  query may have at most one result" error. That fits a target named by
  `"id"`.
- `"reach": [{...}]` returns every match, in order of `steps`, then
  guid; `limit`, `sort`, `optional` and `"return": "count"` work as on
  any list. The three nearest people:

  ```json
  {"id": "/en/michael_stonebraker",
   "reach": [{"step": "...", "type": "/people/person", "name": null,
              "steps": null, "limit": 3}]}
  ```

- More than one search from one object uses MQL's key prefixes:
  `"a:reach"`, `"b:reach"`.

### Rules

- Reads only: `reach` in a write is an error.
- No `reach` inside a step (graphd's rule), and no `reach` as an
  alternative of an "or".
- `as_of_time` applies to the walk too: shortest paths as the graph
  was then.
- Cursors page only MQL's top level, so paging through many matches
  needs `reach` at the top. Paging nested lists can come later.

## Alternative A: a `"*"` marker and an array of nodes

### Full steps

A subquery rooted at the current object, with `"*"` as the value that
marks the next one, as graphd's `(*)` does. From an author, through a
paper, to a co-author:

```json
"step": {"!/dblp/publication/author": {
           "type": "/dblp/publication",
           "name": null,
           "/dblp/publication/author": "*"}}
```

`"*"` isn't a valid id, so it can't currently be the value of an
object property; on a value property it is an error. Each full step,
and each alternative of `step|=` (which can be full steps too), has
exactly one `"*"`. As in graphd, `"*"` stands alone: what the next
object must be is said by the target, not by the step.

### What comes back

- **`path`.** A list of node subqueries, from the start to the match,
  both included (as in graphd). Each asks for that node's fields: `id`,
  `name`, `type`, any property. In every node after the start,
  `"via": null` returns the step's `null`s for the step that reached
  it - which paper links two co-authors:

  ```json
  "path": [{"name": null, "via": null}]
  ->  [{"name": "Michael Stonebraker"},
       {"name": "Jim Gray",
        "via": {"!/dblp/publication/author": {"name": "..."}}},
       ...]
  ```

  `via` holds every way the step can be taken between its two nodes
  (every shared paper), as graphd's `via` does.

- **`paths`.** More than one shortest path per match:
  `"paths": [{"path": [{"id": null}], "limit": 3}]` returns up to three
  (`limit` defaults to MQL's 100, and compiles to graphd's
  `pathlimit`); `"paths": {"return": "count"}` returns how many there
  are.

### An example, compiled

Stonebraker to Knuth, co-author by co-author, with the paper behind
each step:

```json
{"id": "/en/michael_stonebraker",
 "reach": {"step": {"!/dblp/publication/author":
                      {"name": null, "/dblp/publication/author": "*"}},
           "id": "/en/donald_knuth",
           "steps": null,
           "path": [{"name": null, "via": null}]}}
```

compiles to about:

```
read (guid=<stonebraker> result=((contents))
  (<-path step=(result=(contents)
                 (<-right typeguid=<author> result=((contents))
                    left->(result=((name))
                       (<-left typeguid=<author> result=none right->(*)))))
          guid=<knuth> result=((steps (path via)))))
```

with the names of the path's nodes read as pymql reads any result's.

## Alternative B: nested steps and nested results

### Full steps

A full step is the plain MQL query for one step from the current
object, and its innermost object is the next object. There is no
marker. From an author, through a paper, to a co-author:

```json
"step": {"!/dblp/publication/author": {
           "name": null,
           "/dblp/publication/author": {"type": "/people/person",
                                        "name": null}}}
```

On its own, that is the query for "my co-authors", and it can be tried
as one; `reach` repeats it.

- **A step is a chain.** Each object in it has at most one object
  subquery, and the end of the chain is the next object. A side object
  can still be read as a value (`"venue": null` returns its id). A step
  that branches is an error naming both candidates for the next object.
  This is also what graphd's fast chain walk needs.
- **Conditions on every node.** Constraints in the innermost object -
  `"type": "/people/person"` above - hold for every node the path
  passes through and for the match. graphd's `*` stands alone, so pymql
  writes them in two places in the graphd query, and graphd applies
  both: on the step's root, so graphd won't pass through a node that
  fails them (the start included: if it fails them there are no
  paths), and among the `<-path` constraint's own constraints, so
  graphd won't match one (a node failing the root's constraints can
  otherwise still be reached and matched).
- **What each node returns.** The innermost object's `null`s are what
  each node on the path returns; the `null`s between the current
  object and the innermost one (the paper's `name`) are what each step
  passes through. There is no `via` key.

### What comes back

`"path": null` returns the path nested: the step's result, with the
next step merged into the next object beside that object's own fields,
until the innermost object is the match. It is what MQL would return
for the step written out by hand `steps` times:

```json
"reach": {"id": "/en/donald_knuth", "steps": 3,
  "path": {"!/dblp/publication/author": {"name": "On XML and Databases",
            "/dblp/publication/author": {"name": "Dan Suciu",
              "!/dblp/publication/author": {"name": "The Seattle Report",
                "/dblp/publication/author": {"name": "Christos Papadimitriou",
                  "!/dblp/publication/author": {"name": "...",
                    "/dblp/publication/author": {"name": "Donald Knuth"}}}}}}}}}
```

- The start is the object around `reach`, which the outer query
  already returns; the target's fields and `steps` stay at the top of
  `reach`, so a client needn't walk to the bottom for them.
- With `step|=`, each level is keyed by the alternative that matched
  (graphd's `via` reports the first that matches), which says which way
  that step went.
- The next step's first key sits beside the next object's own fields;
  if the innermost object asks for a field under that same key, it is
  an error, and a key prefix (`"a:..."`) avoids it.

### Every way through a step

A middle object follows the usual MQL rule:

- `{...}` returns the first way the step can be taken between its two
  nodes (the first shared paper).
- `[{...}]` returns every way, and each carries its own copy of the
  rest of the path - as plain MQL returns a list of papers, each with
  its own co-author subquery:

  ```json
  "path": {"!/dblp/publication/author": [
    {"name": "On XML and Databases",
     "/dblp/publication/author": {"name": "Dan Suciu",
       "!/dblp/publication/author": [ ...rest of the path... ]}},
    {"name": "Another Shared Paper",
     "/dblp/publication/author": {"name": "Dan Suciu",
       "!/dblp/publication/author": [ ...the same rest... ]}}]}
  ```

  graphd's `via` already holds every way, so this needs nothing more
  from graphd. The copies multiply step by step (with 4, 2 and 5
  shared papers on three steps, the last step appears 8 times), so a
  `"limit"` in the middle list bounds the ways shown per step.
- `"return": "count"` in a middle list is an error: it would collapse
  the papers to a number, leaving the rest of the path nowhere to go.

### Several paths per match

`"paths": null` returns the same shape, with each step's key holding a
list: paths that begin alike share a branch, so the paths form a tree.
Every level is a list, branching or not, so clients see one shape.
`"paths": {"limit": 3}` takes the first three paths (graphd's
`pathlimit=3`); `"paths": {"return": "count"}` returns how many there
are. graphd orders a match's paths from the match backwards, so pymql
groups them by their beginnings to make the tree.

### Where the result comes from

graphd returns each path's nodes and, for each step, its `via`: the
step template read with its root bound to the step's start and `*` to
its end. The innermost object's fields are compiled onto the step's
root, so each node's fields come back in the `via` of the step leaving
it, and the match's from the `<-path` constraint's own result. pymql
nests what graphd returns, with no further reads.

### An example, compiled

```json
{"id": "/en/michael_stonebraker",
 "reach": {"step": {"!/dblp/publication/author":
                      {"name": null,
                       "/dblp/publication/author": {"name": null}}},
           "id": "/en/donald_knuth",
           "steps": null,
           "path": null}}
```

compiles to about:

```
read (guid=<stonebraker> result=((contents))
  (<-path step=(result=(name contents)
                 (<-right typeguid=<author> result=((contents))
                    left->(result=((name))
                       (<-left typeguid=<author> result=none right->(*)))))
          guid=<knuth> result=((name steps (path via)))))
```

## A and B compared

| | A | B |
|---|---|---|
| Next object in a full step | `"*"`, which `"*": null` already means otherwise | the innermost object |
| Conditions on each node | not in the step | in the innermost object |
| A step on its own | not a valid query | the query for one step |
| Step shape | any template with one `"*"` | a chain |
| Path | array of nodes | nested, the step repeated |
| What a step passed through | `via`, every way | the middle objects; `[{}]` for every way |
| Several paths | a list of arrays | a tree |
| Reserved keys | `step`, `steps`, `path`, `paths`, `via` | `step`, `steps`, `path`, `paths` |
| Client walking a path | iterate an array | descend; a flatten helper for list views |
| Result size | linear in the path | can multiply with `[{}]` and `paths` |

## Open questions

1. **A or B.**
2. **The name `reach`.** Not `path`, which is wanted inside the clause
   and is a likely property name. A bare directive shadows a short-form
   property of the same name on the type around it, as `limit` does.
   The alternative is a reflection property, `/type/reflect/reach`,
   which can't collide but is long; or both, `reach` as the short form
   of `/type/reflect/reach`, as `id` is of `/type/object/id`.
3. **In A, `"*"` as the next-object marker.** It mirrors graphd's
   `(*)`. The alternative, a reserved key (`{"/dblp/publication/author":
   {"next": true}}`), is less like graphd and also collides with a
   possible property name. B needs neither.
4. **Reserved keys inside `reach`.** They shadow target properties
   with those short names; those are written in full, as with `id` and
   `type` today. Putting the target in a key of its own (`"to": {...}`)
   would avoid that, at the cost of nesting and of moving the
   one-or-many choice onto `to`.

## B as implemented

On the `reach-b` branch: `mql/hijson.py` (`resolve_reach()`,
`add_query_primitive_reach()`) and `mql/readqp.py` (`PathQP`), tested
by `test/reach_live_test.py` on the small graph of
`test/path_fixture.py`. Everything above for B works as written; where
the proposal left a choice open, the implementation takes these:

- **A simple step** `"P"` is `{"P": {"id": null}}`: each level of a
  path gives the node's id, and the next step beside it.
- **The step's outermost object** holds only the property it starts
  with. That property is resolved on `/type/object`, so it is written as
  a full id (or a `/type/object` or reflection property).
- **Finding the chain.** The step is resolved as plain MQL first. The
  next object at each level is the one object subquery written as `{...}`
  or `[{...}]` (`{}` counts, and means the default properties, as in
  plain MQL); values, and objects read as values (`"venue": null`), don't
  count. `"type": {...}` would count, so write `"type": "/t"`.
- **Directives.** None in the innermost object (it is a node, not a
  result list); in a middle object, `limit` and `sort` but not
  `optional`, `return` or `count` (every step is taken). No `id` with a
  value in the innermost object, since it would hold for every node.
- **`step|=`**: each alternative is one branch of a graphd "or" (one
  alternative needs no "or"), and all must end in the same innermost
  object, since it is compiled once, on the step's root.
- **`{...}` in the middle** is the first way through the step (graphd's
  `pagesize=1` on that link, which the walk ignores).
- **`"steps": 3`** is echoed in the result, as MQL echoes constraints.
- **`paths`**: `null` (up to 100 paths, MQL's default limit),
  `{"limit": n}`, or `{"return": "count"}`. Each level of the tree is in
  order of the guid of the node its steps reach. `path` and `paths` can
  be asked for together.
- **`return`** can name a reach clause's `steps`, `path` and `paths`, as
  well as its target's keys: `"return": "steps"`, or
  `"return": ["name", "reach.steps"]` from outside.

### The query

For a step `{"!author": [{"name": null, "author": {"name": null}}]}`,
pymql writes:

- the step's root: the innermost object's keys (`name` on each node),
  then the chain to `*`, `right->(*)` or `left->(*)` by direction, in a
  branch of its own;
- on the `<-path` constraint: the target's keys, then a second copy of
  the innermost object's keys (so the match meets its conditions, and
  returns its fields at the end of the path);
- `result=((steps path via ...))`, or `(path via)` in a list for
  `paths`, with `pathlimit`.

Each element of `via` is graphd's reply to the step template, so pymql
parses it with the same code as any reply (`parse_result_node()` on the
step's root), takes the alternative whose entry isn't `null`, and
nests: the next node's fields and step go where the step's `*` was.
Steps with the same two ends are parsed once.

### Speed

graphd's fast walks (the chain walk, and searching from both ends) need
each constraint in the step to have exactly one subconstraint, the next
link. In MQL, reading a field such as `name` is an optional
subconstraint (a link to the name), so a step that returns fields isn't
a chain, and graphd falls back to its general walk, from one end.

So when the clause asks for neither `path` nor `paths`, nothing reads
what the step returns, and pymql drops the optional subconstraints from
the step (and from the match's copy of the innermost object). On dblp,
Stonebraker to Knuth (3 steps) takes 0.14 s that way, with or without
`name`s in the step. With `"path": null` and names in the step, the same
search had not finished when it hit an 8-second timeout.

Returning paths quickly needs graphd's chain test
(`route_collect()` in `graphd-read-path.c`) to skip optional
subconstraints, which can't change what a step reaches. The walking
copy of the step could also drop them (`walk_rewrite()`). This affects A
just as much: its `via` reads the middle objects' fields the same way.
