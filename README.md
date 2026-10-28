# MQL, the Metaweb Query Language

This repository contains the original implementation of the Metaweb Query
Language, written in Python.

## Requirements

* Python 3 (tested with 3.9)
* [absl-py](https://pypi.org/project/absl-py/), and
  [PyYAML](https://pypi.org/project/PyYAML/) for the tests
* A running [graphd](https://github.com/google/graphd), to run queries.
  The tests don't need one.

MQL is imported as the package `pymql`, so this repository must be checked out
in a directory named `pymql`, and that directory's parent must be on
`PYTHONPATH`. The commands below are run from the parent directory:

```
$ git clone https://github.com/google/pymql
$ python3 -m venv venv
$ venv/bin/pip install absl-py==2.1.0 PyYAML==6.0.1
$ export PYTHONPATH=$PWD
```

The Bazel `BUILD` files date from the Python 2 version and haven't been
updated.

## Running graphd

Build graphd as described in its `BUILDING.md`, then start it in the
foreground, listening on port 8100:

```
$ graphd/out/bin/graphd -n -d /tmp/data-dir -p /tmp/graphd.pid -i tcp://127.0.0.1:8100
```

## Bootstrapping a graphd for MQL

An empty graphd has to be bootstrapped with the core types MQL needs before it
can answer MQL queries. In another terminal, run:

```
$ venv/bin/python pymql/bootstrap/bootstrap.py --graphd_addr=localhost:8100 \
    --load pymql/bootstrap/otg.bootstrap
```

This takes about a second, and logs a `graph.request.start` and
`graph.request.end` line for each of its graphd requests. Bootstrapping a graph
that isn't empty fails.

## Running MQL queries

`mqlbin.py` runs a single MQL read or write:

```
$ venv/bin/python pymql/mqlbin.py --graphd_addr=localhost:8100 \
    --mqlcmd=read '{"id": "/type/object/type", "guid": null}'
<logs...>
MQLResult(result={'guid': '#0f01a8c040007309800000000000000c', 'id': '/type/object/type'}, cost=..., dateline=None, cursor=None)
```

Writes need a user, given in `--mqlenv`. The user must belong to a group
that has write permission; in a freshly bootstrapped graph, `/user/metaweb`
does:

```
$ venv/bin/python pymql/mqlbin.py --graphd_addr=localhost:8100 \
    --mqlcmd=write --mqlenv '{"$user": "/user/metaweb"}' \
    '{"create": "unless_exists", "id": null, "name": "Example",
      "type": "/type/namespace", "key": {"namespace": "/en", "value": "example"}}'
<logs...>
MQLResult(result={'create': 'created', 'id': '/en/example', 'name': 'Example', 'type': '/type/namespace', 'key': {'namespace': '/en', 'value': 'example'}}, cost=..., dateline=..., cursor=None)
```

## Running the tests

The tests in `test/` replay graphd responses recorded from the Freebase graph
in `test/data/*.yaml`, so they don't need a graphd. Run each test file in its
own process, since a process loads only one recording:

```
$ for t in pymql/test/*_test.py; do venv/bin/python $t; done
```

Some tests are expected to fail:

| Test file                  | Expected failures |
|----------------------------|-------------------|
| `basic_mql_test.py`        | 2 |
| `best_hrid_test.py`        | 3 |
| `cost_test.py`             | 1 |
| `mids_test.py`             | 9 |
| `mql_exceptions_test.py`   | 3 |
| `mql_manual_test.py`       | 2 |
| `mql_manual_write_test.py` | 2 |
| `regression_misc_test.py`  | 3 |

`best_hrid_test.py` and `mql_exceptions_test.py` have no recordings; they
only run against a live Freebase graph. The other failures are tests whose
expected results, or whose graphd queries, changed after their recordings were
made.

To run tests against a live graphd instead, pass `--mockmode=nomock
--graphd_addr=host:port`, or `--mockmode=record` to re-record a test file's
responses. Most tests expect Freebase data, so they fail against a freshly
bootstrapped graph.

## History

This code was originally authored by Tim Sturge, then maintained by Warren
Harris after his departure.

Dime ("2 MQL's") was the implementation written by Warren in OCaml that offered
significant improvements over this initial implementation. However, when Metaweb
was acquired by Google nearing the end of the productionization of Dime, it was
only used partially until Freebase was turned down a few years later. In the
meantime, Warren had gone on to develop other tools used during the early days
of the Knowledge Graph projects at Google.
