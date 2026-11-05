# Code map

What each part of the tree does, in the order a query meets it. "Live"
means used by `MQLService` today; the rest is kept from the Freebase
service and doesn't import as it stands.

## The path of a query

| Module | Role |
|---|---|
| `__init__.py` | `MQLService`: `read()` and `write()`, keyword options to a varenv, `MQLResult` |
| `mqlbin.py` | A command line around `MQLService` |
| `mql/env.py` | `Varenv`, the per-request environment (`$user`, `$permission` defaulting to `/boot/all_permission`, `$lang`...); `LookupManager` and the deferred id and guid placeholders |
| `mql/hijson.py` | `HighQuery`: MQL itself. Parsing into clauses, resolving types and properties, directives, comparisons, sort and `return`; for reads, building `ReadQP` trees and the result; for writes, lowering to low JSON and building the result |
| `mql/readqp.py` | `ReadQP` and `FinalQP`: one graphd constraint each, for reads; generate graphd text and parse replies into MQL results |
| `mql/lojson.py` | `LowQuery`: low JSON, the graph-shaped query language under MQL. Reads, and the whole write pipeline: implied writes, primitives, prepares, access checks, the writes, results |
| `mql/qprim.py` | `QueryPrimitive`: one node or link of a low-JSON query or write; its states, its prepare read, its graphd write and `unique=` clause |
| `mql/scope.py` | Permissions: `check_write_defaults()`, `check_permission()`, `Permission`, and the `Privileged` and `Authority` sentinels |
| `mql/schema.py` | `SchemaFactory`, `SchemaDomain`, `SchemaType`, `SchemaProperty`: loading and caching the schema, categories, property lookup, value coercion and comparators |
| `mql/lookup.py` | `NamespaceFactory`: ids, guids and mids in both directions, with the guid-to-id cache and the choice of the best id |
| `mql/namespace.py` | `NameMap` and `Namespace`: key-by-key id resolution with cached namespaces; `BootNamespace` finds the root by graphd names |
| `mql/mid.py` | Mid encoding and decoding |
| `mql/graph/connector.py` | `GraphConnector`: request modifiers (`cost`, `dateline`, `asof`, `id`), costs, policies, `read_varenv()` and `write_varenv()` |
| `mql/graph/conn_tcp.py` | `TcpGraphConnector`: graphd over TCP, server choice, timeouts and retries |
| `mql/graph/conn_mock.py` | Connectors that replay or record graphd traffic, for the tests |
| `mql/grparse.py` | Parses graphd replies into nested Python lists |
| `mql/grquoting.py` | Quotes and unquotes graphd strings |
| `mql/utils.py` | `QueryDict` and `QueryList`, the modes (`ReadMode`, `WriteMode`, `CheckMode`, `PrepareMode`), the key and id regular expressions, cursor encoding |
| `mql/error.py` | `MQLError` and its subclasses, with the clause each happened in |
| `error.py`, `tid.py`, `log/` | Parameterised exceptions, transaction ids, logging |
| `util/` | Key quoting (`keyquote.py`: `$XXXX` escapes), datetimes, small helpers |
| `bootstrap/` | `bootstrap.py`, and `otg.bootstrap`: the core graph an empty graphd needs |

## Not live

| Path | What it was |
|---|---|
| `api/` | The Freebase web service layer: JSON envelopes (`mqlread`'s `query`, `cursor`, `code`), caching of high- and low-level queries, content serving. It imports `mw.mql` and uses Python 2's `unicode`. |
| `emql/` | Extended MQL: properties computed by adapters calling outside services (docs in `emql/docs/emql.txt`). Also Python 2 and `mw.` imports. |
| `formats/` | Content types for the web service |
| `mql/pathexpr.py` | Debug output for the old web service |
| `mql/benchmark.py` | An old benchmark driver |
| `BUILD`, `WORKSPACE`, `bazel/` | Bazel files from the Python 2 version, not updated |

## Tests

`test/` (see the README for running them):

- **Unit tests**, no graphd: `grparse_test.py`, `grquoting_test.py`,
  `keyquote_test.py`, `mid_codec_test.py`, `utils_test.py`.
- **`live_graphd_test.py`**: starts a graphd, bootstraps it, reads
  and writes.
- **The rest**: MQL queries with expected results, whose graphd traffic
  is replayed from `test/data/*.yaml` (recorded from Freebase), through
  `mql_fixture.py` and `conn_mock.py`. A replayed request must match a
  recording up to the order of its terms, so a change in how MQL
  writes graphd queries shows up as a missing recording, even when the
  answer would be the same; `--mockmode=record` re-records against a
  live graph.
