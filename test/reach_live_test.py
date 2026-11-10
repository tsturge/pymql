# -*- coding: utf-8 -*-
"""The "reach" directive (path search) against a real graphd.

Starts a bootstrapped graphd as live_graphd_test does, loads the small
co-author graph of path_fixture.py, and runs reach queries: the directive
compiles to graphd's <-path constraint, and its results are checked against
hand-worked answers, and paths against the same steps written out by hand in
plain MQL.
"""

import pymql
from pymql.mql import error
from pymql.test import path_fixture
from pymql.test.live_graphd_test import GraphdTestCase

from absl.testing import absltest

NS = path_fixture.NS
A = NS + '/paper/author'
K = NS + '/person/knows'


def pid(key):
  return NS + '/' + key


# From an author, through a paper, to a co-author.
COAUTHOR = {'!' + A: {'name': None, A: {'name': None}}}


class ReachTest(GraphdTestCase):

  @classmethod
  def setUpClass(cls):
    super(ReachTest, cls).setUpClass()
    path_fixture.load(pymql.MQLService(connector=cls.conn))

  def reach(self, start, reach, **env):
    return self.read({'id': pid(start), 'reach': reach}, **env)['reach']

  def testSimpleStep(self):
    self.assertEqual(
        self.reach('alice', {
            'step': K,
            'id': pid('dave'),
            'name': None,
            'steps': None,
            'path': None
        }), {
            'id': pid('dave'),
            'name': 'Dave',
            'steps': 3,
            'path': {K: {'id': pid('bob'),
                         K: {'id': pid('carol'),
                             K: {'id': pid('dave')}}}},
        })

  def testAlternativesSayWhichWay(self):
    # Either way along knows, nearest first; each level is keyed by the
    # alternative that matched.
    result = self.reach('bob', [{
        'step|=': [K, '!' + K],
        'name': None,
        'steps': None,
        'path': None
    }])
    self.assertEqual(result, [
        {'name': 'Alice', 'steps': 1, 'path': {'!' + K: {'id': pid('alice')}}},
        {'name': 'Carol', 'steps': 1, 'path': {K: {'id': pid('carol')}}},
        {'name': 'Dave', 'steps': 2,
         'path': {K: {'id': pid('carol'), K: {'id': pid('dave')}}}},
    ])

  def testFullStep(self):
    self.assertEqual(
        self.reach('alice', {
            'step': COAUTHOR,
            'id': pid('carol'),
            'steps': None,
            'path': None
        }), {
            'id': pid('carol'),
            'steps': 2,
            'path': {'!' + A: {
                'name': 'Paper One',
                A: {'name': 'Bob',
                    '!' + A: {'name': 'Paper Two',
                              A: {'name': 'Carol'}}}}},
        })

  def testEveryWayThroughAStep(self):
    # [{...}] in the middle returns every shared paper, each with its own
    # copy of the rest of the path; a limit bounds them.
    step = {'!' + A: [{'name': None, A: {'name': None}}]}
    result = self.reach('alice', {
        'step': step, 'id': pid('carol'), 'path': None})
    rest = {'name': 'Carol'}
    self.assertEqual(result['path'], {'!' + A: [{
        'name': 'Paper One',
        A: {'name': 'Bob',
            '!' + A: [{'name': 'Paper Two', A: rest},
                      {'name': 'Paper Three', A: rest}]}}]})

    step['!' + A][0]['limit'] = 1
    result = self.reach('alice', {
        'step': step, 'id': pid('carol'), 'path': None})
    self.assertEqual(
        result['path']['!' + A][0][A]['!' + A],
        [{'name': 'Paper Two', A: rest}])

  def testPathIsTheStepWrittenOutByHand(self):
    # The same query, through the same nodes, as plain MQL.
    step = {'!' + A: [{'name': None, A: {'id': None, 'name': None}}]}
    result = self.reach('alice', {
        'step': step, 'id': pid('dave'), 'steps': None, 'path': None})
    self.assertEqual(result['steps'], 2)

    path = result['path']
    erin = path['!' + A][0][A]['id']
    by_hand = self.read({
        'id': pid('alice'),
        '!' + A: [{'name': None, A: {
            'id': erin, 'name': None,
            '!' + A: [{'name': None, A: {'id': pid('dave'), 'name': None}}]}}],
    })
    self.assertEqual(path, {'!' + A: by_hand['!' + A]})

  def testConditionsHoldOnEveryNode(self):
    # Reviewers only: around erin, so three steps instead of two.
    step = {'!' + A: {A: {'type': NS + '/reviewer', 'name': None}}}
    result = self.reach('alice', {
        'step': step, 'id': pid('dave'), 'steps': None, 'path': None})
    self.assertEqual(result['steps'], 3)
    names = []
    level = result['path']
    while level:
      node = level['!' + A][A]
      names.append(node['name'])
      self.assertEqual(node['type'], NS + '/reviewer')
      level = node if '!' + A in node else None
    self.assertEqual(names, ['Bob', 'Carol', 'Dave'])

    # ... and on the start: alice isn't named Erin, so no paths.
    step = {'!' + A: {A: {'name': 'Erin'}}}
    self.assertIsNone(
        self.read({'id': pid('alice'), 'reach': {'step': step, 'id': None}}))

  def testNearestAndDistance(self):
    bare = {'!' + A: {A: {}}}
    self.assertEqual(
        self.reach('alice', [{
            'step': bare, 'type': NS + '/person', 'name': None,
            'steps': None, 'limit': 3
        }]), [
            {'type': NS + '/person', 'name': 'Bob', 'steps': 1},
            {'type': NS + '/person', 'name': 'Erin', 'steps': 1},
            {'type': NS + '/person', 'name': 'Carol', 'steps': 2},
        ])
    self.assertEqual(
        self.reach('alice', {'step': bare, 'steps<=': 1, 'return': 'count'}),
        2)
    self.assertEqual(
        self.reach('alice', [{'step': bare, 'steps': 2, 'name': None}]),
        [{'name': 'Carol', 'steps': 2}, {'name': 'Dave', 'steps': 2}])
    self.assertEqual(
        self.reach('alice', [{'step': bare, 'name': None, 'return': 'name',
                              'steps>': 1}]), ['Carol', 'Dave'])

  def testSeveralPaths(self):
    reach = {'step': COAUTHOR, 'id': pid('carol')}
    self.assertEqual(
        self.reach('alice', dict(reach, paths={'return': 'count'})),
        {'id': pid('carol'), 'paths': 2})

    tree = {'!' + A: [
        {'name': 'Paper One',
         A: {'name': 'Bob',
             '!' + A: [{'name': 'Paper Two', A: {'name': 'Carol'}}]}},
        {'name': 'Paper Five',
         A: {'name': 'Erin',
             '!' + A: [{'name': 'Paper Seven', A: {'name': 'Carol'}}]}},
    ]}
    self.assertEqual(self.reach('alice', dict(reach, paths=None))['paths'],
                     tree)
    self.assertEqual(
        self.reach('alice', dict(reach, paths={'limit': 1}))['paths'],
        {'!' + A: tree['!' + A][:1]})

    # A path is the first of them.
    result = self.reach('alice', dict(reach, path=None, paths=None))
    self.assertEqual(result['path']['!' + A]['name'], 'Paper One')

  def testOneMatchOrMany(self):
    with self.assertRaises(error.MQLTooManyValuesForUniqueQuery):
      self.reach('alice', {'step': K, 'name': None})

    # frank knows nobody: optional gives None, otherwise frank doesn't match.
    self.assertEqual(
        self.read({'id': pid('frank'), 'name': None,
                   'reach': {'step': K, 'name': None, 'optional': True}}),
        {'id': pid('frank'), 'name': 'Frank', 'reach': None})
    self.assertIsNone(
        self.read({'id': pid('frank'), 'reach': {'step': K, 'name': None}}))

  def testPrefixesNestingAndLists(self):
    self.assertEqual(
        self.read({
            'id': pid('alice'),
            'a:reach': {'step': K, 'id': pid('carol'), 'steps': None},
            'b:reach': {'step': {'!' + A: {A: {}}}, 'id': pid('dave'),
                        'steps': None},
        }), {
            'id': pid('alice'),
            'a:reach': {'id': pid('carol'), 'steps': 2},
            'b:reach': {'id': pid('dave'), 'steps': 2},
        })

    self.assertEqual(
        self.reach('alice', {
            'step': K, 'id': pid('bob'), 'steps': None,
            'reach': {'step': K, 'id': pid('dave'), 'steps': None}
        }), {'id': pid('bob'), 'steps': 1,
             'reach': {'id': pid('dave'), 'steps': 2}})

    self.assertEqual(
        self.read([{
            'type': NS + '/reviewer', 'name': None, 'sort': 'name',
            'reach': {'step': K, 'id': pid('dave'), 'steps': None,
                      'optional': True},
            'return': ['name', 'reach.steps'],
        }]), [['Alice', 3], ['Bob', 2], ['Carol', 1], ['Dave', None],
              ['Frank', None]])

    # "return" can name what a reach clause returns.
    self.assertEqual(
        self.reach('alice', [{'step': K, 'steps': None, 'return': 'steps'}]),
        [1, 2, 3])

  def testAsOfTime(self):
    # A link written after the fixture isn't there as of the fixture.
    before = self.read({
        'id': pid('carol'), K: {'id': pid('dave'), 'link': {'timestamp': None}}
    })[K]['link']['timestamp']
    self.write({'id': pid('erin'), K: {'connect': 'insert', 'id': pid('frank')}})

    reach = {'step': K, 'id': pid('frank'), 'steps': None, 'optional': True}
    self.assertEqual(self.reach('erin', reach),
                     {'id': pid('frank'), 'steps': 1})
    self.assertIsNone(self.reach('erin', reach, as_of_time=before))

  def testErrors(self):
    cases = [
        ({'id': None}, 'needs a step'),
        ({'step': K, 'step|=': [K]}, "both 'step' and 'step\\|='"),
        ({'step|=': []}, 'non-empty list'),
        ({'step': 3}, 'A step is a property'),
        ({'step': {K: None}}, 'Write the object a step reaches'),
        ({'step': {K: {}, 'name': None}}, 'holds only the property'),
        ({'step': {'!' + A: {A: {}, '/type/object/type': {}}}},
         'must be a chain'),
        ({'step': {K: {K: None}}, 'path': None}, 'next step'),
        ({'step|=': [K, {'!' + K: {'name': None}}]},
         'end in the same innermost object'),
        ({'step': {K: {'reach': {'step': K}}}}, "Can't use reach in a step"),
        ({'step': {K: {'name': None, 'limit': 3}}}, 'innermost object'),
        ({'step': {'!' + A: {'optional': True, A: {}}}}, 'every step is taken'),
        ({'step': {'!' + A: [{'return': 'count', A: {}}]}},
         'every step is taken'),
        ({'step': {K: {'id': pid('bob')}}}, "Can't give an id"),
        ({'step': K, 'path': {}}, "'path' must be null"),
        ({'step': K, 'paths': {'limit': 0}}, 'positive integer'),
        ({'step': K, 'paths': {'return': 'name'}}, 'paths must be'),
        ({'step': K, 'steps': 0}, "'steps' must be"),
        ({'step': K, 'steps<=': -1}, 'non-negative'),
    ]
    for reach, message in cases:
      with self.subTest(reach=reach):
        with self.assertRaisesRegex(error.MQLParseError, message):
          self.read({'id': pid('alice'), 'reach': reach})

    with self.assertRaisesRegex(error.MQLParseError, 'object clause'):
      self.read({'id': pid('alice'), 'name': {'value': None,
                                               'reach': {'step': K}}})
    with self.assertRaisesRegex(error.MQLParseError, 'takes a subquery'):
      self.read({'id': pid('alice'), 'reach': [{'step': K}, {'step': K}]})
    with self.assertRaisesRegex(error.MQLParseError, 'only in a read'):
      self.write({'id': pid('alice'), 'reach': {'step': K}})


if __name__ == '__main__':
  absltest.main()
