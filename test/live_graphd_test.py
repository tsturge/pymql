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


if __name__ == '__main__':
  absltest.main()
