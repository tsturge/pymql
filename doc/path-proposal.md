# Path search in MQL: a proposal

Status: a proposal, not implemented. It builds on graphd's `<-path`
constraint (graphd's `doc/path-proposal.md`), which is implemented: MQL
would compile to it, and graphd needs nothing new. Three choices are
still open; they are at the end.

## Why

graphd can find shortest paths: from an object, by a step - a pattern
from one object to the next - to the nearest objects that match a
constraint, or a named one. MQL can't ask for them, so the one client
that wants them, the mql-browser's path view, sends graphd queries
directly, around MQL and its schema. With MQL syntax, clients write
steps as properties, targets as ordinary subqueries, and get answers in
MQL's terms (ids, names, types).

## The shape

A new read directive, `"reach"`, holds a subquery for the objects
reachable from the object around it:

```json
{
  "id": "/en/michael_stonebraker",
  "reach": {
    "step|=": ["/dblp/publication/author", "!/dblp/publication/author"],
    "id": "/en/donald_knuth",
    "name": null,
    "steps": null,
    "path": [{"id": null, "name": null}]
  }
}
```

Inside `reach`, four keys are reserved - `step`, `steps`, `path` and
`paths`. Everything else is an ordinary MQL subquery on the target:
`id`, `name`, `type`, any property, nested subqueries. They pick which
objects match, and their `null`s return values, as anywhere in MQL.

| MQL | graphd |
|---|---|
| `"reach": {...}` | `(<-path ...)` |
| `step` | `step=((...))` |
| `"steps<=": 6` | `steps<=6` |
| the target's constraints | the `<-path` constraint's own |
| `"steps": null` | the `steps` result atom |
| `"path": [...]` | the `path` result atom, and reads of its nodes' fields |
| `"paths": [...]` with `limit` | a list of paths, with `pathlimit` |
| `"paths": {"return": "count"}` | `path-count` |

## Steps

Three forms, from the shortest:

- **One property.** `"step": "/people/person/parents"` follows the
  link forward; `"step": "!/people/person/parents"` follows it
  backward.
- **Alternatives.** MQL's `|=` takes any one of several:
  `"step|=": ["/dblp/publication/author", "!/dblp/publication/author"]`
  goes either way along author links. With the reflection properties,
  `"step|=": ["/type/reflect/any_master", "/type/reflect/any_reverse"]`
  is any link, either way - the browser's path view without "via".
- **Full form.** A subquery rooted at the current object, with `"*"` as
  the value that marks the next one, as graphd's `(*)` does. From an
  author, through a paper, to a co-author:

  ```json
  "step": {"!/dblp/publication/author": {
             "type": "/dblp/publication",
             "name": null,
             "/dblp/publication/author": "*"}}
  ```

  `"*"` isn't a valid id, so it can't currently be the value of an
  object property; on a value property it is an error. Each full form,
  and each alternative of `step|=` (which can be full forms too), has
  exactly one `"*"`.

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
step=((result=(contents)
       {(<-left  typeguid=P result=((name)) right->(*))} |
       {(<-right typeguid=P result=((name)) left->(*))}))
```

graphd walks the alternatives as a union, and follows an "or" whose
branches are each a chain through its chain walk, from one end or both:
on dblp, either way along author links from Stonebraker to Knuth takes
0.07 s warm, 2.8 s cold. `via` reports the first alternative that
matches, so MQL can return it under that alternative's own key
(`"/dblp/publication/author"` or `"!/dblp/publication/author"`), and a
client can tell which way each step went.

## What comes back

- **`steps`.** `"steps": null` returns the distance; `"steps<=": 6`
  (or `<`, `>`, `>=`), or `"steps": 3`, constrains it. As in graphd,
  that is the shortest distance.
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

- **`paths`.** More than one shortest path per match:
  `"paths": [{"path": [{"id": null}], "limit": 3}]` returns up to three
  (`limit` defaults to MQL's 100, and compiles to graphd's
  `pathlimit`); `"paths": {"return": "count"}` returns how many there
  are.

## One match or many

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

## Rules

- Reads only: `reach` in a write is an error.
- No `reach` inside a step (graphd's rule), and no `reach` as an
  alternative of an "or".
- `as_of_time` applies to the walk too: shortest paths as the graph
  was then.
- Cursors page only MQL's top level, so paging through many matches
  needs `reach` at the top. Paging nested lists can come later.

## An example, compiled

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
  (<-path step=((result=(contents)
                  (<-right typeguid=<author> result=((name)) left->(*))))
          guid=<knuth> result=((steps (path via)))))
```

with the names of the path's nodes read as pymql reads any result's.

## Open questions

1. **The name `reach`.** Not `path`, which is wanted inside the clause
   and is a likely property name. A bare directive shadows a short-form
   property of the same name on the type around it, as `limit` does.
   The alternative is a reflection property, `/type/reflect/reach`,
   which can't collide but is long.
2. **`"*"` as the next-object marker.** It mirrors graphd's `(*)`. The
   alternative, a reserved key (`{"/dblp/publication/author":
   {"next": true}}`), is less like graphd and also collides with a
   possible property name.
3. **Reserved keys inside `reach`.** `step`, `steps`, `path` and
   `paths` shadow target properties with those short names; those are
   written in full, as with `id` and `type` today.
