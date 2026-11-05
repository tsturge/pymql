# How MQL works

MQL, the Metaweb Query Language, is how Freebase was queried: a query
is a JSON object shaped like the answer you want, with `null`s and
empty lists where you want values filled in. This directory explains
how this implementation turns such a query into requests to graphd and
the replies back into JSON.

The full language reference is the MQL manual (the `mql-manual`
repository: `MQLReferenceGuide.pdf` and `html/`). These pages describe
the language only as far as is needed to explain the implementation,
and point into the code.

- [The language](language.md): query by example, ids, types and
  properties, values, directives, comparisons, writes.
- [MQL on graphd](graph-model.md): how objects, properties, names,
  types, keys and permissions are stored as graphd primitives, and how
  MQL finds its way in.
- [Reads](reads.md): one read followed through every stage, with the
  graphd request it becomes.
- [Writes](writes.md): `create` and `connect`, the reads a write makes
  first, and the graphd write it becomes.
- [Schema, ids and caches](schema-and-ids.md): how types and properties
  are loaded and resolved, how ids become guids and back, and what is
  cached.
- [Code map](code-map.md): every module, what it does, and which parts
  are live.
- [Path search](path-proposal.md): a proposed `reach` directive for
  shortest paths. Not implemented.

The examples are real: the graphd requests and replies were captured
from this code, reading a graph loaded with Freebase Easy data and
writing to a freshly bootstrapped one. Guids are shortened or replaced
by the ids they stand for, as noted where it matters.
