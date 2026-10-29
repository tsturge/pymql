# -*- coding: utf-8 -*-
"""MQL reads and writes against a real, freshly bootstrapped graphd.

The other tests replay recorded graphd responses. This one starts its own
graphd on a free port in a temporary directory, bootstraps it with
bootstrap/otg.bootstrap, and runs queries through the TCP connector, so it
exercises the whole stack, writes included.

The graphd binary comes from --graphd_binary, else $GRAPHD, else
../graphd/out/bin/graphd next to this repository (the Make build). The
tests are skipped if there is no binary.
"""

import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

import pymql
from pymql.bootstrap import bootstrap
from pymql.mql import error
from pymql.mql import graph

from absl import flags
from absl.testing import absltest

FLAGS = flags.FLAGS

_PYMQL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

flags.DEFINE_string(
    'graphd_binary',
    os.environ.get(
        'GRAPHD',
        os.path.join(
            os.path.dirname(_PYMQL_DIR), 'graphd', 'out', 'bin', 'graphd')),
    'graphd binary to start for the live tests')

USER = {'$user': '/user/metaweb'}


def _free_port():
  s = socket.socket()
  s.bind(('127.0.0.1', 0))
  port = s.getsockname()[1]
  s.close()
  return port


class LiveGraphdTest(absltest.TestCase):

  @classmethod
  def setUpClass(cls):
    super(LiveGraphdTest, cls).setUpClass()
    if not os.access(FLAGS.graphd_binary, os.X_OK):
      raise unittest.SkipTest('no graphd binary at %s' % FLAGS.graphd_binary)

    cls.tmpdir = tempfile.mkdtemp(prefix='pymql-live-')
    port = _free_port()
    # graphd writes debug logs to its current directory.
    cls.graphd = subprocess.Popen(
        [FLAGS.graphd_binary, '-n',
         '-d', os.path.join(cls.tmpdir, 'db'),
         '-p', os.path.join(cls.tmpdir, 'graphd.pid'),
         '-i', 'tcp://127.0.0.1:%d' % port],
        cwd=cls.tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
      deadline = time.time() + 10
      while True:
        try:
          socket.create_connection(('127.0.0.1', port), 0.1).close()
          break
        except OSError:
          if cls.graphd.poll() is not None or time.time() > deadline:
            raise RuntimeError('graphd did not start')
          time.sleep(0.05)

      cls.conn = graph.TcpGraphConnector(addrs=[('127.0.0.1', port)])
      boot = bootstrap.Bootstrap(cls.conn)
      boot.load_from_file(
          os.path.join(_PYMQL_DIR, 'bootstrap', 'otg.bootstrap'))
      boot.load_bootstrap()
      boot.load_root_user()
      boot.load_object_hints()
    except:
      cls._StopGraphd()
      raise

  @classmethod
  def tearDownClass(cls):
    cls._StopGraphd()
    super(LiveGraphdTest, cls).tearDownClass()

  @classmethod
  def _StopGraphd(cls):
    cls.graphd.terminate()
    cls.graphd.wait()
    shutil.rmtree(cls.tmpdir, ignore_errors=True)

  def setUp(self):
    # A new service per test: MQLService caches namespace contents,
    # and a deleted key stays in the cache of the service that saw it.
    self.mql = pymql.MQLService(connector=self.conn)

  def read(self, query, **env):
    return self.mql.read(query, **env).result

  def write(self, query, **env):
    env = dict(USER, **env)
    return self.mql.write(query, **env).result

  def fresh_read(self, query):
    return pymql.MQLService(connector=self.conn).read(query).result

  def create_namespace(self, parent, key, **extra):
    query = {
        'create': 'unless_exists',
        'id': None,
        'type': '/type/namespace',
        'key': {'namespace': parent, 'value': key},
    }
    query.update(extra)
    return self.write(query)

  def testReadBootstrappedSchema(self):
    result = self.read({'id': '/type/object/type', 'guid': None})
    self.assertEqual(result['id'], '/type/object/type')
    self.assertRegex(result['guid'], '^#[0-9a-f]{32}$')

  def testReadMissingIdIsNone(self):
    self.assertIsNone(self.read({'id': '/en/no_such_thing', 'name': None}))

  def testUnknownPropertyIsATypeError(self):
    with self.assertRaises(error.MQLTypeError):
      self.read({'id': '/type/object/type', 'no_such_property': None})

  def testWriteNeedsAUser(self):
    with self.assertRaises(error.MQLAccessError):
      self.mql.write({'create': 'unconditional', 'type': '/type/namespace'})

  def testCreateUnlessExists(self):
    first = self.create_namespace('/en', 'live_create', name='Created')
    self.assertEqual(first['create'], 'created')
    self.assertEqual(first['id'], '/en/live_create')
    second = self.create_namespace('/en', 'live_create', name='Created')
    self.assertEqual(second['create'], 'existed')

    result = self.read({'id': '/en/live_create', 'name': None, 'type': []})
    self.assertEqual(result, {
        'id': '/en/live_create',
        'name': 'Created',
        'type': ['/type/namespace'],
    })

  def testUnicodeName(self):
    self.create_namespace('/en', 'live_unicode')
    name = u'Caf\xe9 \u2603 \U0001F600'
    result = self.write({
        'id': '/en/live_unicode',
        'name': {'value': name, 'lang': '/lang/en', 'connect': 'update'},
    })
    # There was no name to update.
    self.assertEqual(result['name']['connect'], 'inserted')
    self.assertEqual(
        self.fresh_read({'id': '/en/live_unicode', 'name': None})['name'],
        name)

  def testUpdateReplacesUniqueValue(self):
    self.create_namespace('/en', 'live_update', name='Before')
    result = self.write({
        'id': '/en/live_update',
        'name': {'value': 'After', 'lang': '/lang/en', 'connect': 'update'},
    })
    self.assertEqual(result['name']['connect'], 'updated')
    result = self.fresh_read(
        {'id': '/en/live_update', 'name': [{'value': None}]})
    self.assertEqual(result['name'], [{'value': 'After'}])

  def testKeysSortLimitCount(self):
    self.create_namespace('/en', 'live_keys')
    for key in ['c', 'a', 'b']:
      self.create_namespace('/en/live_keys', key)

    result = self.read({
        'id': '/en/live_keys',
        '/type/namespace/keys': [{'value': None, 'sort': 'value', 'limit': 2}],
    })
    self.assertEqual(result['/type/namespace/keys'],
                     [{'value': 'a'}, {'value': 'b'}])

    result = self.read({
        'id': '/en/live_keys',
        '/type/namespace/keys': [{'value': None, 'sort': '-value'}],
    })
    self.assertEqual(result['/type/namespace/keys'],
                     [{'value': 'c'}, {'value': 'b'}, {'value': 'a'}])

    result = self.read({
        'id': '/en/live_keys',
        '/type/namespace/keys': {'value': None, 'return': 'count'},
    })
    self.assertEqual(result['/type/namespace/keys'], 3)

  def testListQuery(self):
    self.create_namespace('/en', 'live_list')
    for key in ['y', 'x']:
      self.create_namespace('/en/live_list', key)
    result = self.read([{
        'type': '/type/namespace',
        'key': {'namespace': '/en/live_list', 'value': None},
        'id': None,
        'sort': 'key.value',
    }])
    self.assertEqual([r['id'] for r in result],
                     ['/en/live_list/x', '/en/live_list/y'])

  def testDeleteKey(self):
    self.create_namespace('/en', 'live_delete')
    self.create_namespace('/en/live_delete', 'gone')
    result = self.write({
        'id': '/en/live_delete/gone',
        'key': {'namespace': '/en/live_delete', 'value': 'gone',
                'connect': 'delete'},
    })
    self.assertEqual(result['key']['connect'], 'deleted')
    self.assertIsNone(self.fresh_read({'id': '/en/live_delete/gone'}))
    self.assertEqual(
        self.fresh_read({
            'id': '/en/live_delete',
            # Without optional, no keys would mean no match at all.
            '/type/namespace/keys': [{'value': None, 'optional': True}],
        })['/type/namespace/keys'], [])

  def testReturnKey(self):
    self.create_namespace('/en', 'live_result')
    for key in ['q', 'p']:
      self.create_namespace('/en/live_result', key, name=key.upper())

    query = [{
        'type': '/type/namespace',
        'key': {'namespace': '/en/live_result', 'value': None},
        'name': None,
        'sort': 'key.value',
        'return': 'name',
    }]
    self.assertEqual(self.read(query), ['P', 'Q'])

    # Nested, on a single clause, and on a link-valued property.
    result = self.read({
        'id': '/en/live_result',
        '/type/namespace/keys': [{
            'value': None,
            'sort': 'value',
            'return': 'value'
        }],
        'return': '/type/namespace/keys',
    })
    self.assertEqual(result, ['p', 'q'])

    # The named key can be a clause with its own result.
    result = self.read({
        'id': '/en/live_result/p',
        'key': {'namespace': None, 'value': None, 'return': 'namespace'},
        'return': 'key',
    })
    self.assertEqual(result, '/en/live_result')

    # "count" and "estimate-count" keep their old meaning.
    result = self.read({
        'id': '/en/live_result',
        '/type/namespace/keys': {'value': None, 'return': 'count'},
    })
    self.assertEqual(result['/type/namespace/keys'], 2)

    # An object renames the keys it lists, and drops the rest.
    query = [{
        'type': '/type/namespace',
        'key': {'namespace': '/en/live_result', 'value': None},
        'name': None,
        'id': None,
        'sort': 'key.value',
        'return': {'the_name': 'name', 'the_type': 'type', 'key': 'key'},
    }]
    self.assertEqual(self.read(query), [
        {'the_name': 'P', 'the_type': '/type/namespace',
         'key': {'namespace': '/en/live_result', 'value': 'p'}},
        {'the_name': 'Q', 'the_type': '/type/namespace',
         'key': {'namespace': '/en/live_result', 'value': 'q'}},
    ])

    # Objects nest, and can name a key twice.
    result = self.read({
        'id': '/en/live_result',
        'name': None,
        '/type/namespace/keys': [{
            'value': None,
            'sort': 'value',
            'return': {'k': 'value', 'again': 'value'}
        }],
        'return': {'keys': '/type/namespace/keys'},
    })
    self.assertEqual(result, {'keys': [{'k': 'p', 'again': 'p'},
                                       {'k': 'q', 'again': 'q'}]})

    # An array returns the values in its order.
    query = [{
        'type': '/type/namespace',
        'key': {'namespace': '/en/live_result', 'value': None},
        'name': None,
        'id': None,
        'sort': 'key.value',
        'return': ['id', 'name'],
    }]
    self.assertEqual(self.read(query), [['/en/live_result/p', 'P'],
                                        ['/en/live_result/q', 'Q']])
    query[0]['return'] = ['name']
    self.assertEqual(self.read(query), [['P'], ['Q']])

    # Arrays nest, inside objects too.
    result = self.read({
        'id': '/en/live_result',
        'name': None,
        '/type/namespace/keys': [{
            'value': None,
            'namespace': None,
            'sort': 'value',
            'return': ['value', 'namespace']
        }],
        'return': {'keys': '/type/namespace/keys', 'n': 'name'},
    })
    self.assertEqual(result, {
        'keys': [['p', '/en/live_result/p'], ['q', '/en/live_result/q']],
        'n': None,
    })

    # A clause that matches nothing is still None.
    self.assertIsNone(self.read({'id': '/en/no_such_thing', 'name': None,
                                 'return': 'name'}))

  def assertReturns(self, query, project, expected):
    """Checks query's "return" against the same query without it.

    project(clause_result) builds what "return" should give for one result
    of the outermost clause, from the result of the query without "return".
    """
    without = dict(query[0] if isinstance(query, list) else query)
    del without['return']
    plain = self.read([without] if isinstance(query, list) else without)
    if isinstance(query, list):
      projected = [project(r) for r in plain]
    else:
      projected = None if plain is None else project(plain)

    result = self.read(query)
    self.assertEqual(result, projected)
    self.assertEqual(result, expected)

  def testReturnPath(self):
    # The properties of /type/object, sorted by name. Each property's
    # schema and expected type are unique; so is each type's domain.
    props = {
        'type': '/type/property',
        'name': None,
        'schema': {'id': '/type/object', 'name': None},
        'sort': 'name',
        'limit': 2,
    }

    query = [dict(props, **{'return': 'schema.name'})]
    self.assertReturns(query, lambda r: r['schema']['name'],
                       ['Object', 'Object'])

    # Paths in an array, two levels deep, mixed with plain keys.
    query = [dict(props, **{
        'expected_type': {'id': None, 'domain': {'name': None}},
        'return': ['name', 'expected_type.id', 'expected_type.domain.name'],
    })]
    self.assertReturns(
        query, lambda r: [r['name'], r['expected_type']['id'],
                          r['expected_type']['domain']['name']],
        [['attribution', '/type/attribution', 'Metaweb System Types'],
         ['creator', '/type/user', 'Metaweb System Types']])

    # Paths in an object, through full property ids.
    query = [dict(props, **{
        '/type/property/expected_type': {
            'id': None,
            '/type/type/domain': {'id': None}
        },
        'return': {
            'prop': 'name',
            'domain': '/type/property/expected_type./type/type/domain.id',
        },
    })]
    self.assertReturns(
        query, lambda r: {
            'prop': r['name'],
            'domain': r['/type/property/expected_type']
                      ['/type/type/domain']['id'],
        },
        [{'prop': 'attribution', 'domain': '/type'},
         {'prop': 'creator', 'domain': '/type'}])

    # Through a link clause.
    query = [dict(props, **{
        'schema': {'id': '/type/object', 'link': {'timestamp': None}},
        'return': 'schema.link.timestamp',
    })]
    result = self.read(query)
    self.assertLen(result, 2)
    for timestamp in result:
      self.assertRegex(timestamp, r'^\d{4}-\d\d-\d\dT')
    self.assertReturns(query, lambda r: r['schema']['link']['timestamp'],
                       result)

    # Into a text value.
    query = {
        'id': '/type/object',
        'type': '/type/type',
        'name': {'value': None, 'lang': None},
        'return': ['name.value', 'name.lang'],
    }
    self.assertReturns(query, lambda r: [r['name']['value'],
                                         r['name']['lang']],
                       ['Object', '/lang/en'])

    # The path can end at a clause whose own sub-queries have a return.
    query = {
        'id': '/type/object/name',
        'type': '/type/property',
        'schema': {
            'id': None,
            'properties': [{'name': None, 'sort': 'name', 'limit': 2,
                            'return': 'name'}],
        },
        'return': 'schema.properties',
    }
    self.assertEqual(self.read(query), ['attribution', 'creator'])

    # Inside a list clause, a path per element.
    query = {
        'id': '/type/object',
        'type': '/type/type',
        'properties': [{
            'name': None,
            'expected_type': {'id': None},
            'sort': 'name',
            'limit': 2,
            'return': 'expected_type.id',
        }],
        'return': 'properties',
    }
    self.assertEqual(self.read(query),
                     ['/type/attribution', '/type/user'])

    # On data we wrote: each namespace's unique key.
    self.create_namespace('/en', 'live_path')
    for key in ['b', 'a']:
      self.create_namespace('/en/live_path', key)
    query = [{
        'type': '/type/namespace',
        'key': {'namespace': '/en/live_path', 'value': None},
        'id': None,
        'sort': 'key.value',
        'return': ['id', 'key.value', 'key.namespace'],
    }]
    self.assertReturns(
        query, lambda r: [r['id'], r['key']['value'], r['key']['namespace']],
        [['/en/live_path/a', 'a', '/en/live_path'],
         ['/en/live_path/b', 'b', '/en/live_path']])

  def testReturnPathThroughMissingClause(self):
    props = {
        'type': '/type/property',
        'name': None,
        'schema': {'id': '/type/object'},
        'sort': 'name',
        'limit': 2,
    }
    # An optional unique clause that doesn't match gives None, at any depth.
    query = [dict(props, **{
        'expected_type': {
            'id': None,
            'optional': True,
            'domain': {'name': 'no such domain'}
        },
        'return': ['name', 'expected_type.id', 'expected_type.domain.name'],
    })]
    self.assertEqual(self.read(query),
                     [['attribution', None, None], ['creator', None, None]])

    # So does a forbidden one.
    query = [dict(props, **{
        'expected_type': {'id': '/type/text', 'optional': 'forbidden'},
        'return': 'expected_type.id',
    })]
    self.assertEqual(self.read(query), [None, None])

  def testReturnPathErrors(self):
    base = {
        'type': '/type/property',
        'name': None,
        'limit': 1,
    }
    cases = [
        ({'schema': [{'id': None}]}, 'schema.id',
         "'schema' .* must be a unique sub-query"),
        ({'schema': None}, 'schema.id', "'schema' .* not a value"),
        ({'schema': '/type/object'}, 'schema.id', "'schema' .* not a value"),
        ({'schema': {}}, 'schema.id', "'schema' .* not a value"),
        ({'schema': {'id': None, 'return': 'id'}}, 'schema.id',
         "'schema' .* has a 'return' of its own"),
        ({'schema': {'id': None}}, 'schema.name',
         "'name' .* not a key returned"),
        ({'schema': {'id': None, '*': None}}, 'schema.name',
         "'name' .* not a key returned"),
        ({'schema': {'id': None}}, 'bogus.id', "'bogus' .* not a key"),
        ({'schema': {'id': None}}, 'schema.', "'' .* not a key"),
        ({'schema': {'id': None}}, '.schema', "'' .* not a key"),
        ({'schema': {'id': None}}, 'schema..id', "'' .* not a key"),
        ({'schema': {'id': None, 'limit': 1}}, 'schema.limit',
         "'limit' .* not a key"),
        ({'schema': {'id': None, 'name~=': '*'}}, 'schema.name~=',
         "'name~=' .* not a key"),
        ({'schema': {'id': None, 'name': None}}, 'schema.name.value',
         "'name' .* not a value"),
        ({'schema': {'id': None, 'count': None}}, 'schema.count',
         "'count' .* not a key"),
    ]
    for extra, path, message in cases:
      for ret in (path, [path], {'x': path}):
        query = dict(base, **extra)
        query['return'] = ret
        with self.assertRaisesRegex(error.MQLParseError, message,
                                    msg=repr(query)):
          self.read(query)

  def testReturnKeyErrors(self):
    bad = [
        # Not a key of the clause.
        {'id': '/type/object/type', 'name': None, 'return': 'guid'},
        # Not something the clause returns.
        {'id': '/type/object/type', 'name': None, 'limit': 1,
         'return': 'limit'},
        {'id': '/type/object/type', 'name': None, 'return': []},
        {'id': '/type/object/type', 'name': None,
         'return': ['name', 'guid']},
        {'id': '/type/object/type', 'name': None,
         'return': ['name', ['name']]},
        {'id': '/type/object/type', 'name': None, 'return': {}},
        {'id': '/type/object/type', 'name': None, 'return': {'g': 'guid'}},
        {'id': '/type/object/type', 'name': None,
         'return': {'n': 'name', 'l': 'limit'}},
        {'id': '/type/object/type', 'name': None,
         'return': {'n': {'m': 'name'}}},
    ]
    for query in bad:
      with self.assertRaises(error.MQLParseError, msg=repr(query)):
        self.read(query)

    with self.assertRaises(error.MQLParseError):
      self.write({'id': '/type/object/type', 'name': None, 'return': 'name'})
    with self.assertRaises(error.MQLParseError):
      self.write({'id': '/type/object/type', 'name': None,
                  'return': {'n': 'name'}})


if __name__ == '__main__':
  absltest.main()
