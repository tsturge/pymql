# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Connector classes for mocked graphd query and response strings.

Use these connectors when using the pymql library.
See test/mql_fixture.py in pymql for a reference
of how to use the record and replay connectors.
"""

__author__ = 'bneutra@google.com (Brendan Neutra)'
import sys
import hashlib
import re
import time
from pymql.mql import error
from pymql.mql.graph.connector import GraphConnector
from pymql.mql.grparse import ReplyParser
from absl import logging


class GraphMockException(Exception):
  pass


TIMEOUT_POLICIES = {
    'default': {
        'timeout': 8.0,
        'stubby_deadline': 10.0,
        'fail_fast': False,
    },
    'bootstrap': {
        'timeout': 2.0,
        'stubby_deadline': 4.0,
        'fail_fast': False,
    },
}


class MockRecordConnector(GraphConnector):
  """Mock connector for recording graphd responses.

  This class will append to the mockdata dictionary that it
  is handed. It interacts with a slightly modified
  live connector that you specify
  (e.g. the mock stubby connector)
  See test/mql_fixture.py for an implentation example.
  """

  def __init__(self, mockdata, connector, **kwargs):

    if not kwargs.get('policy_map', None):
      kwargs['policy_map'] = TIMEOUT_POLICIES
    GraphConnector.__init__(self, **kwargs)
    self.mockdata = mockdata
    self._conn = connector
    self._conn._save_raw_response = True
    self._mocked = {}

  def open(self, policy=None):

    self._conn.open(policy)

  def transmit_query(self, q, policy, deadline, **kwargs):

    try:
      result = self._conn.transmit_query(q, policy, deadline)
    except error.MQLTimeoutError:
      self.gen_mock_data(q, self._conn._raw_response)
      self.totalcost = self._conn.totalcost
      raise

    self.gen_mock_data(q, self._conn._raw_response)
    self.totalcost = self._conn.totalcost
    return result

  def reset_cost(self):
    if hasattr(self, '_conn'):
      self._conn.reset_cost()

  def gen_mock_data(self, q, result):

    k, hsh = strip_mock_query(q)
    if hsh in self._mocked:
      # if a query has been seen before, assume it needs another
      # version of the response mocked.
      self._mocked[hsh] += 1
      hsh = hsh + '_' + str(self._mocked[hsh])
    else:
      self._mocked[hsh] = 0
    self.mockdata[hsh] = [k, result]


class MockReplayConnector(GraphConnector):
  """Mock connector for recording graphd responses.

  This class will read from the mockdata dictionary that it
  is handed. It doesn't connect or interact with graphd.
  It's faster and more reliable than talking to a live db.
  See test/mql_fixture.py for an implentation example.
  """

  def __init__(self, mockdata):
    # don't connect to a graph, do not call __init__
    self.no_timeouts = False
    self.totalcost = {}
    self.mockdata = mockdata
    self._mocked = {}

  def open(self, policy=None):
    pass

  def transmit_query(self, q, policy, deadline, **kwargs):
    start_time = time.time()
    logging.debug('mocking query: %s', q)
    k, _ = strip_mock_query(q)

    # Recordings are matched on the query's canonical form, because the
    # order of terms in generated queries follows dict iteration order,
    # which differs between the recording Python and this one.
    canon = canonical_query(k)
    n = self._mocked.get(canon, -1) + 1
    self._mocked[canon] = n

    recorded = _canonical_index(self.mockdata).get(canon, {}).get(n)
    if recorded is None:
      msg = 'NO MOCKED REPONSE for this query: %s' % k
      logging.error(msg)
      raise GraphMockException(msg)

    rec_query, reply = recorded
    logging.debug('mock query found: %s', rec_query)
    logging.debug('mock response found: %s', reply)
    if rec_query != k:
      reply = remap_reply(rec_query, k, reply)
    rg = re.search(' dateline\=\"(\S+)\" ', reply)
    self.dateline = None
    if rg:
      self.dateline = rg.groups()[0]

    reply_parser = ReplyParser()
    reply_parser.parse_full_reply(reply)
    ret = reply_parser.get_reply()
    dbtime = time.time() - start_time
    self.add_graph_costs(ret.cost, dbtime, tries=1)
    return ret

  def _get_policy(self, policy=None):
    return None


def strip_mock_query(q):
  # strip off the id
  # note the query may be spread over multiple lines
  # but the directives should be on the first one.
  k = re.sub(' (id=\S+) ', ' ', q, count=1)
  # the recordings predate the tu= cost limit, which doesn't change results
  k = re.sub('^(\w+) cost="[^"]*" ', r'\1 cost="" ', k, count=1)
  # and were made without passing write datelines on to later reads
  k = re.sub('^(\w+ cost="") dateline="[^"]*" ', r'\1 dateline="" ', k,
             count=1)

  # exception cases
  # timestamp stuff generated when creating mock responses is fine when it
  # comes time to replay, but mql does a scope query in realtime, not sure why
  # TODO(bneutra): why must MQL do this?
  p = re.compile('timestamp\>20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d.\d+ ')
  if re.search(p, k):
    logging.debug('we saw a timestamp in the query %s', k)
  k = re.sub(p, 'timestamp>2010-09-23T00:00:00.000001 ', k)

  h = hashlib.sha1()
  h.update(k.encode('utf-8', 'surrogateescape'))
  hsh = h.hexdigest()
  return k, hsh


# Order-insensitive matching of graphd queries against recordings.
#
# A graphd query is a tree of constraints. Within a constraint the order of
# terms and subconstraints doesn't change which primitives match, but it
# does change the layout of the reply: result=(...) fields come back in the
# order they were asked for, and "contents" expands to one value per
# subconstraint, in query order. A write reply is (guid sub1 sub2 ...).
# canonical_query() sorts all of that away, and remap_reply() rearranges a
# recorded reply to match the layout of an equivalent query.

_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+(?:"(?:\\.|[^"\\])*")?')


class _Bind(object):
  """A prefix bound to a parenthesized list: key=(...) or left->(...)."""

  def __init__(self, prefix, items):
    self.prefix = prefix
    self.items = items


def _parse(s):
  stack = [[]]
  depth = 1
  for tok in _TOKEN_RE.findall(s):
    if tok == '(':
      stack.append([])
      depth = max(depth, len(stack))
    elif tok == ')':
      if len(stack) == 1:
        raise GraphMockException('unbalanced ) in %s' % s)
      items = stack.pop()
      parent = stack[-1]
      if (parent and isinstance(parent[-1], str) and
          (parent[-1].endswith('=') or parent[-1].endswith('->'))):
        parent[-1] = _Bind(parent[-1], items)
      else:
        parent.append(items)
    else:
      stack[-1].append(tok)
  if len(stack) != 1:
    raise GraphMockException('unbalanced ( in %s' % s)
  # the canonicalizing and remapping below recurse a few frames per level
  if sys.getrecursionlimit() < 4 * depth + 100:
    sys.setrecursionlimit(4 * depth + 100)
  return stack[0]


def _serialize(item):
  if isinstance(item, list):
    return '(' + ' '.join(_serialize(i) for i in item) + ')'
  return item


def _split_constraint(items):
  """Returns (terms, result template or None, whether bare, subconstraints).

  A bare template, result=x rather than result=(x), lays its values out
  unwrapped in its parent's reply.
  """
  terms, result, bare, subs = [], None, False, []
  for item in items:
    if isinstance(item, list):
      subs.append(item)
    elif isinstance(item, _Bind) and item.prefix == 'result=':
      result = item.items
    elif isinstance(item, str) and item.startswith('result='):
      result, bare = [item[len('result='):]], True
    elif isinstance(item, _Bind) and item.prefix.endswith('->'):
      subs.append(item)
    else:
      terms.append(item)
  return terms, result, bare, subs


def _canon_list(items):
  return '(' + ' '.join(sorted(_canon_term(i) for i in items)) + ')'


def _canon_term(item):
  if isinstance(item, _Bind):
    return item.prefix + _canon_list(item.items)
  if isinstance(item, list):
    return _canon_list(item)
  return item


def _canon_sub(sub):
  if isinstance(sub, _Bind):
    return sub.prefix + _canon_constraint(sub.items)
  return _canon_constraint(sub)


def _canon_constraint(items):
  terms, result, bare, subs = _split_constraint(items)
  parts = sorted(_canon_term(t) for t in terms)
  if bare:
    parts.append('result=' + result[0])
  elif result is not None:
    parts.append('result=' + _canon_list(result))
  parts.extend(sorted(_canon_sub(s) for s in subs))
  return '(' + ' '.join(parts) + ')'


def canonical_query(q):
  """A form of the graphd query q that ignores the order of terms."""
  items = _parse(q)
  if items and isinstance(items[-1], list):
    return ' '.join(sorted(_canon_term(i) for i in items[:-1]) +
                    [_canon_constraint(items[-1])])
  return ' '.join(_canon_term(i) for i in items)


def _sub_items(sub):
  return sub.items if isinstance(sub, _Bind) else sub


class _ReplyMismatch(Exception):
  pass


def _width(items, mode):
  """How many values a constraint contributes to its parent's reply."""
  _, result, bare, subs = _split_constraint(items)
  if mode == 'write' or not bare:
    return 1
  if result[0] == 'contents':
    return sum(_width(_sub_items(s), mode) for s in subs)
  return 1


def _remap_constraint(rec, our, values, mode):
  """Rearrange values, recorded for constraint rec, to fit constraint our.

  values is the list of values the constraint contributes to its
  parent's reply (see _width); the result is the same for our.
  """
  _, rec_result, rec_bare, rec_subs = _split_constraint(rec)
  _, our_result, our_bare, our_subs = _split_constraint(our)
  if len(rec_subs) != len(our_subs) or rec_bare != our_bare:
    raise _ReplyMismatch('constraint shape')

  # pair each of our subconstraints with an equivalent recorded one
  unused = {}
  for i, sub in enumerate(rec_subs):
    unused.setdefault(_canon_sub(sub), []).append(i)
  pairing = []
  for sub in our_subs:
    candidates = unused.get(_canon_sub(sub))
    if not candidates:
      raise _ReplyMismatch('unpaired subconstraint')
    pairing.append(candidates.pop(0))
  rec_items = [_sub_items(sub) for sub in rec_subs]
  our_items = [_sub_items(sub) for sub in our_subs]
  widths = [_width(items, mode) for items in rec_items]

  def remap_contents(rec_values):
    """Our subconstraints' values, from the recorded ones."""
    if len(rec_values) != sum(widths):
      raise _ReplyMismatch('contents length')
    per_sub, pos = [], 0
    for w in widths:
      per_sub.append(rec_values[pos:pos + w])
      pos += w
    out = []
    for j, i in enumerate(pairing):
      out.extend(_remap_constraint(rec_items[i], our_items[j], per_sub[i],
                                   mode))
    return out

  if mode == 'write':
    # (guid sub1 sub2 ...)
    value = values[0]
    if not isinstance(value, list):
      return values
    return [value[:1] + remap_contents(value[1:])]

  if rec_result is None or our_result is None:
    # the default result doesn't include contents; layouts agree
    return values
  if rec_bare:
    return _remap_template(rec_result, our_result, values, remap_contents)
  if not isinstance(values[0], list):
    return values
  return [_remap_template(rec_result, our_result, values[0], remap_contents)]


def _remap_template(rec_tmpl, our_tmpl, value, remap_contents):
  if not isinstance(value, list):
    return value
  rec_names = [i for i in rec_tmpl if not isinstance(i, list)]
  if len(set(rec_names)) != len(rec_names):
    if rec_tmpl == our_tmpl:
      return value
    raise _ReplyMismatch('repeated result field')
  rec_inner = [i for i in rec_tmpl if isinstance(i, list)]
  our_inner = [i for i in our_tmpl if isinstance(i, list)]
  if len(rec_inner) != len(our_inner) or len(rec_inner) > 1:
    raise _ReplyMismatch('result template shape')

  # Take the recorded value apart according to the recorded template.
  # A nested list in a template means "one entry per match", and
  # "contents" stands for the values of all the subconstraints.
  fields, contents, matches = {}, None, None
  pos = 0
  ncontents = len(value) - (len(rec_tmpl) - 1)
  for item in rec_tmpl:
    if isinstance(item, list):
      matches = [
          _remap_template(item, our_inner[0], m, remap_contents)
          for m in value[pos:]
      ]
      pos = len(value)
    elif item == 'contents':
      contents = remap_contents(value[pos:pos + ncontents])
      pos += ncontents
    else:
      fields[item] = value[pos]
      pos += 1
  if pos != len(value):
    raise _ReplyMismatch('reply length')

  # and put it back together according to ours
  out = []
  for item in our_tmpl:
    if isinstance(item, list):
      out.extend(matches)
    elif item == 'contents':
      out.extend(contents)
    else:
      out.append(fields[item])
  return out


_REPLY_MODIFIER_RE = re.compile(r'^[a-z]+="')


def remap_reply(rec_query, our_query, reply):
  """Rearrange reply, recorded for rec_query, to fit equivalent our_query."""
  rec_items = _parse(rec_query)
  our_items = _parse(our_query)
  reply_items = _parse(reply)
  if (not reply_items or reply_items[0] != 'ok' or
      not isinstance(rec_items[-1], list) or
      not isinstance(our_items[-1], list)):
    return reply
  # ok cost="..." dateline="..." id="..." values...
  start = 1
  while (start < len(reply_items) and isinstance(reply_items[start], str) and
         _REPLY_MODIFIER_RE.match(reply_items[start])):
    start += 1
  mode = 'write' if rec_items[0] == 'write' else 'read'
  try:
    values = _remap_constraint(rec_items[-1], our_items[-1],
                               reply_items[start:], mode)
  except (_ReplyMismatch, IndexError, KeyError) as e:
    raise GraphMockException('cannot fit recorded reply to query (%s): %s' %
                             (e, our_query))
  return ' '.join(_serialize(i) for i in reply_items[:start] + values) + '\n'


_CANONICAL_INDEXES = {}


def _to_str(s):
  # The recordings hold graphd's raw utf-8 bytes, one character per byte.
  try:
    return s.encode('latin-1').decode('utf-8', 'surrogateescape')
  except UnicodeEncodeError:
    return s


def _canonical_index(mockdata):
  """Index recordings by canonical query, then by repeat count."""
  index = _CANONICAL_INDEXES.get(id(mockdata))
  if index is None:
    index = {}
    for key, entry in list(mockdata.items()):
      if not isinstance(entry, list):
        continue  # a test's fuzz value
      n = int(key.split('_')[1]) if '_' in key else 0
      query, reply = [_to_str(s) for s in entry]
      k, _ = strip_mock_query(query)
      index.setdefault(canonical_query(k), {}).setdefault(n, (k, reply))
    _CANONICAL_INDEXES[id(mockdata)] = index
  return index
