# Reads

A read is compiled into one graphd `read` request, plus whatever
lookups of ids and schema it needs that aren't cached. This page
follows one query through every stage.

## The example

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

With the schema and the ids already cached, this is the whole of the
graphd traffic. Guids are replaced by what they stand for:

```
read cost="tu=30" dateline="" id="graph_read;<host>;<pid>;<time>;0037"
(guid=<42> left=null right=null pagesize=100 result=((contents))
  (<-left typeguid=<fbe/film/directed_by> value=null pagesize=100 result=((contents))
     right->(left=null right=null result=((guid contents))
       (<-left typeguid=<type/object/name> right=<lang/en> optional value!=null
          pagesize=100 result=((datatype value)))))
  (<-left typeguid=<fbe/film/genre> value=null optional pagesize=100 result=((contents))
     right->(left=null right=null result=((contents))
       (<-left typeguid=<type/object/name> right=<lang/en> optional value!=null
          pagesize=100 result=((datatype value)))))
  (<-left typeguid=<fbe/film/initial_release_date> optional value!=null
     pagesize=100 result=((datatype value)))
  (<-left typeguid=<type/object/name> right=<lang/en> optional value!=null
     pagesize=100 result=((datatype value)))
  (<-left typeguid=<type/object/type> right=<fbe/film> value=null pagesize=1
     result=(())))
```

```
[[[[[[<Helgeland>, [["string", "\"Brian Helgeland\""]]]]]],
  [[[[[["string", "\"Biographical film\""]]]]],
   [[[[["string", "\"Drama\""]]]]],
   [[[[["string", "\"Sports films\""]]]]]],
  [["timestamp", "\"2013-04-12\""]],
  [["string", "\"42\""]],
  [[]]]]
```

Each MQL key became a subconstraint linked to the film by `<-left`
("links whose left is this"):

- `directed_by`, a list of subqueries, is an object link (`value=null`)
  to a node whose `guid` and name are returned. It is required, because
  a subquery constrains the match.
- `genre: []` is the same, but `optional`, and returns only names.
- `initial_release_date` and `name` are value links: `value!=null`,
  returning the datatype and value. Text names also need
  `right=<lang/en>`.
- `"type": "/fbe/film"` is a required link to a fixed guid that
  returns nothing (`result=(())`).
- `id` was resolved to a guid before the query was written, and comes
  back as given. `"id": null` on the director asked for its guid
  (`result=((guid contents))`), turned back into an id afterwards.

## The stages

`MQLService.read()` (`__init__.py`) turns keyword options into a
varenv (`_fix_varenv`: `user` becomes `$user`, `as_of_time` becomes
`asof`, and so on) and calls `HighQuery.read()` (`mql/hijson.py`):

1. **Environment.** `Varenv` (`mql/env.py`) wraps the options and
   attaches a `LookupManager`, which collects every id the query needs
   resolved, so they can be resolved together.

2. **Parse.** `make_orig()` copies the query into `QueryDict` and
   `QueryList` objects (`mql/utils.py`) that remember their parent
   clause, key and terminal (`N`, `L`, `D`, `V`), and checks the
   directives.

3. **Resolve.** `resolve_names()` walks the clauses:
   - `resolve_types()` decides each clause's type: the `type` it gives,
     or its property's expected type, or `/type/object`;
   - `resolve_property()` turns each key into a `SchemaProperty`:
     full ids, short names on the clause's type, `!` reverses;
   - comparisons (`resolve_comparison()`), `sort` (`resolve_sort()`),
     `macro` and `return` are checked here too.

   This loads any type it meets that isn't cached (one graphd read per
   type). If a type or property isn't found, `resolve_schema()`
   flushes the schema and id caches and tries once more, in case it is
   new.

4. **Build primitives.** `add_query_primitive_root()` and its helpers
   build a tree of `ReadQP` objects (`mql/readqp.py`), one per graphd
   constraint, in categories:
   - `node`, an object;
   - `link`, the link to a subquery's object;
   - `value`, a value link;
   - `directlink`, a `/type/link` root;
   - `index`, an ordered link's position.

   An object clause that only needs an id and has no comparisons or
   sort (`can_make_final()`) gets no node of its own: its link points at
   the guid directly (`FinalQP`). That's the `"type": "/fbe/film"` line
   above. Directives (`add_read_directives()`) become graphd ones:
   - `limit` becomes `pagesize`; the default is 100 everywhere;
   - `optional` becomes `optional`;
   - `count` becomes a `count` result;
   - `sort` becomes `sort=` with a comparator per key.

   Ids in the query become `DeferredGuidLookup` placeholders.

5. **Resolve ids.** `do_mid_to_guid_lookups()`, then
   `do_guid_lookups()`, resolve every placeholder at once: cached ones
   from `NamespaceFactory`'s cache, the rest with one namespace read
   (see [MQL on graphd](graph-model.md)). That's at most two round
   trips, however many ids the query names.

6. **Generate.** `generate_graph_query()` writes the `ReadQP` tree out
   as graphd text.

7. **Send.** `graph_read()` calls `read_varenv()` on the connector
   (`mql/graph/connector.py`), which adds the request's modifiers:
   - `cost="tu=N"`: a limit on graphd's user time, from
     `query_timeout_tu` or the `--graphd_default_query_timeout_tu` flag
     (30 ms);
   - `dateline=`: the client's `write_dateline`, so a read sees the
     client's own writes even on a replica that is behind;
   - `asof=`: from `as_of_time`;
   - `id=`: a transaction id, the `debug_token`, for the logs.

   `TcpGraphConnector` (`conn_tcp.py`) picks a graphd, retries
   according to its policy, and `grparse.py` parses the reply into
   nested lists.

8. **Build the result.** `parse_result_root()` walks the `ReadQP` tree
   and the reply together, building the JSON. Guids that should be
   shown as ids become placeholders again (`DeferredIdLookup`),
   resolved together by `do_guid_to_mid_lookups()` and
   `do_id_lookups()`: one more graphd read if any aren't cached. Then
   they are substituted. Here `pagesize`, uniqueness (`null` must have at
   most one value, `MQLTooManyValuesForUniqueQuery`) and value types
   (`2013-04-12` is a `timestamp`) are checked and converted.

9. **Return.** `apply_return_directives()` applies `return`. The cursor,
   dateline and variables used are exported into the varenv, and
   `MQLService.read()` returns `MQLResult(result, cost, dateline,
   cursor)`; cost is the summed graphd cost of every request made.

## A cold run

The first query against a graphd, with nothing cached, makes many more
requests. For `{"id": "/type/object/type", "guid": null}`:

| Requests | What |
|---|---|
| 0-7 | Namespace bootstrap: the keys of `/type` and `/boot`, and probes for optional names (`extension`, `requires_permission`) |
| 8 | The schema of the whole `/type` domain - every core type, its properties and their flags - in one large read, as the schema factory starts |
| 9 | The id `/type/object/type`, by keys from the root |
| 10 | The query |

Run again in the same process, it is just the last.

## When ids come back

A query that returns objects whose ids aren't cached is followed by one
read that finds them. `[{"type": "/fbe/film_director", "name": null,
"id": null, "!/fbe/film/directed_by": {"return": "count"}, "limit":
3}]` sends the query:

```
(left=null right=null pagesize=3 result=((guid contents))
  (<-right typeguid=<fbe/film/directed_by> value=null result=(count)
     left->(left=null right=null result=(())))
  (<-left optional typeguid=<type/object/name> right=<lang/en> value!=null
     pagesize=100 result=((datatype value)))
  (<-left typeguid=<type/object/type> right=<fbe/film_director> value=null
     pagesize=1 result=(())))
```

The reverse property is `<-right` ... `left->`: links whose right is
the director, and the films at their left, counted. Then, for the three
guids, one read follows `has_key` links backwards up to three
namespaces (and reads each one's type and `best_hrid`), from which
`/en/Adam_McKay` and the others are built.

## Cursors

With `cursor` in the environment (`True` for the first page), the root
`ReadQP` passes graphd a `cursor=`, and the next cursor comes back in
`MQLResult.cursor`. It is graphd's own cursor string, or `False` at the
end.
