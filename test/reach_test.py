# -*- coding: utf-8 -*-
"""Path search with "reach", against a real graphd (doc/path-proposal.md, A).

The graph, a type /en/test/person with a property knows:

  carol -> alice -> bob  -> dave -> frank
                 -> erin -> dave

so alice to frank is three steps, by two shortest paths (through bob,
whose guid is lower, and through erin), and carol is one step from alice
only against the direction of knows.
"""

from pymql.mql import error
from pymql.test import live_graphd_test

from absl.testing import absltest

T = '/en/test/'
PERSON = T + 'person'
KNOWS = PERSON + '/knows'


class ReachTest(live_graphd_test.LiveGraphdTestCase):

  @classmethod
  def setUpClass(cls):
    super(ReachTest, cls).setUpClass()
    test = cls('testSimpleStep')
    test.setUp()
    test.create_namespace('/en', 'test')
    test.write({'create': 'unless_exists', 'id': None, 'type': '/type/type',
                'key': {'namespace': '/en/test', 'value': 'person'}})
    test.write({'create': 'unless_exists', 'id': None,
                'type': '/type/property',
                'key': {'namespace': PERSON, 'value': 'knows'},
                'schema': PERSON, 'expected_type': PERSON})
    # created in this order, so their guids are in this order too
    for name in ('alice', 'bob', 'carol', 'dave', 'erin', 'frank'):
      test.write({'create': 'unless_exists', 'id': None, 'type': PERSON,
                  'name': name.capitalize(),
                  'key': {'namespace': '/en/test', 'value': name}})
    for a, b in (('alice', 'bob'), ('alice', 'erin'), ('bob', 'dave'),
                 ('erin', 'dave'), ('dave', 'frank'), ('carol', 'alice')):
      test.write({'id': T + a, 'type': PERSON,
                  'knows': {'connect': 'insert', 'id': T + b}})

  def reach(self, start, reach, **env):
    return self.read({'id': T + start, 'reach': reach}, **env)['reach']

  def testSimpleStep(self):
    self.assertEqual(
        self.reach('alice', {'step': KNOWS, 'id': T + 'frank',
                             'steps': None,
                             'path': [{'id': None, 'name': None}]}),
        {'id': T + 'frank', 'steps': 3,
         'path': [{'id': T + 'alice', 'name': 'Alice'},
                  {'id': T + 'bob', 'name': 'Bob'},
                  {'id': T + 'dave', 'name': 'Dave'},
                  {'id': T + 'frank', 'name': 'Frank'}]})

  def testReverseStep(self):
    self.assertEqual(
        self.reach('frank', {'step': '!' + KNOWS, 'id': T + 'alice',
                             'steps': None}),
        {'id': T + 'alice', 'steps': 3})
    # forward, carol can't be reached
    self.assertIsNone(
        self.read({'id': T + 'alice',
                   'reach': {'step': KNOWS, 'id': T + 'carol'}}))

  def testShortNameStep(self):
    # a short name is looked up on the type of the clause around reach
    self.assertEqual(
        self.read({'id': T + 'alice', 'type': PERSON,
                   'reach': {'step': 'knows', 'id': T + 'dave',
                             'steps': None}})['reach'],
        {'id': T + 'dave', 'steps': 2})

  def testAlternatives(self):
    # either way along knows; via says which way each step went
    self.assertEqual(
        self.reach('alice', {'step|=': [KNOWS, '!' + KNOWS],
                             'id': T + 'carol', 'steps': None,
                             'path': [{'name': None, 'via': None}]}),
        {'id': T + 'carol', 'steps': 1,
         'path': [{'name': 'Alice'},
                  {'name': 'Carol', 'via': {'!' + KNOWS: '*'}}]})

  def testAlternativeFullSteps(self):
    # forward one link, or back two
    result = self.reach(
        'alice', {'step|=': [KNOWS, {'!' + KNOWS: {'name': None,
                                                   '!' + KNOWS: '*'}}],
                  'id': T + 'carol',
                  'path': [{'name': None, 'via': None}]})
    self.assertEqual(result['path'], [
        {'name': 'Alice'},
        {'name': 'Bob', 'via': {KNOWS: '*'}},
        {'name': 'Carol',
         'via': {'!' + KNOWS: {'name': 'Alice', '!' + KNOWS: '*'}}},
    ])

  def testFullStepVia(self):
    # a step of two links; {} in a step is the first way, [{}] every way
    step = {KNOWS: {'name': None, KNOWS: '*'}}
    self.assertEqual(
        self.reach('alice', {'step': step, 'id': T + 'dave', 'steps': None,
                             'path': [{'name': None, 'via': None}]}),
        {'id': T + 'dave', 'steps': 1,
         'path': [{'name': 'Alice'},
                  {'name': 'Dave', 'via': {KNOWS: {'name': 'Bob', KNOWS: '*'}}}]})
    step = {KNOWS: [{'name': None, KNOWS: '*'}]}
    self.assertEqual(
        self.reach('alice', {'step': step, 'id': T + 'dave',
                             'path': [{'via': None}]})['path'][1],
        {'via': {KNOWS: [{'name': 'Bob', KNOWS: '*'},
                         {'name': 'Erin', KNOWS: '*'}]}})
    # frank is three links from alice: no whole number of two-link steps
    self.assertIsNone(
        self.read({'id': T + 'alice',
                   'reach': {'step': step, 'id': T + 'frank'}}))

  def testStepFieldsAreReadLater(self):
    # "name": null in a step would make graphd's step an optional
    # subconstraint, and not a chain; it is read after the search instead
    gql = self.mql.high_querier.to_gql(
        None,
        {'id': T + 'alice',
         'reach': {'step': {KNOWS: {'name': None, KNOWS: '*'}},
                   'id': T + 'dave', 'path': [{'via': None}]}}, {})
    self.assertNotIn('optional', gql)
    self.assertIn('result=((guid contents))', gql)
    # short names in a step are looked up as in the step, and returned as
    # written
    result = self.read({
        'id': T + 'alice', 'type': PERSON,
        'reach': {'step': {'knows': {'name': None, 'id': None,
                                     'knows': '*'}},
                  'id': T + 'dave', 'path': [{'via': None}]}})
    self.assertEqual(result['reach']['path'][1]['via'],
                     {'knows': {'name': 'Bob', 'id': T + 'bob',
                                'knows': '*'}})

  def testNearest(self):
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name': None, 'steps': None,
                              'limit': 3}]),
        [{'name': 'Bob', 'steps': 1}, {'name': 'Erin', 'steps': 1},
         {'name': 'Dave', 'steps': 2}])
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name': None, 'steps<=': 1}]),
        [{'name': 'Bob'}, {'name': 'Erin'}])
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name': None, 'steps': 2}]),
        [{'name': 'Dave'}])
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'return': 'count'}]), [4])

  def testUniqueTargetWithManyMatches(self):
    with self.assertRaises(error.MQLTooManyValuesForUniqueQuery):
      self.reach('alice', {'step': KNOWS, 'name': None})

  def testPaths(self):
    result = self.reach('alice', {
        'step': KNOWS, 'id': T + 'frank',
        'paths': [{'path': [{'name': None}], 'limit': 5}]})
    self.assertEqual(result['paths'], [
        {'path': [{'name': 'Alice'}, {'name': 'Bob'}, {'name': 'Dave'},
                  {'name': 'Frank'}]},
        {'path': [{'name': 'Alice'}, {'name': 'Erin'}, {'name': 'Dave'},
                  {'name': 'Frank'}]},
    ])
    result = self.reach('alice', {
        'step': KNOWS, 'id': T + 'frank',
        'paths': [{'path': [{'id': None}], 'limit': 1}]})
    self.assertLen(result['paths'], 1)
    self.assertEqual(
        self.reach('alice', {'step': KNOWS, 'id': T + 'frank',
                             'paths': {'return': 'count'}}),
        {'id': T + 'frank', 'paths': 2})

  def testPathOfIds(self):
    self.assertEqual(
        self.reach('alice', {'step': KNOWS, 'id': T + 'dave',
                             'path': [{}]})['path'],
        [{'id': T + 'alice'}, {'id': T + 'bob'}, {'id': T + 'dave'}])

  def testOptional(self):
    self.assertEqual(
        self.read({'id': T + 'carol',
                   'reach': {'step': KNOWS, 'id': T + 'carol',
                             'optional': True}}),
        {'id': T + 'carol', 'reach': None})
    # the start never matches
    self.assertIsNone(
        self.read({'id': T + 'carol',
                   'reach': {'step': KNOWS, 'id': T + 'carol'}}))

  def testReturn(self):
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name': None, 'steps': None,
                              'return': ['name', 'steps']}]),
        [['Bob', 1], ['Erin', 1], ['Dave', 2], ['Frank', 3]])

  def testPrefixesAndManyStarts(self):
    result = self.read([{
        'type': PERSON, 'name': None,
        'a:reach': {'step': KNOWS, 'id': T + 'frank', 'steps': None},
        'b:reach': {'step': '!' + KNOWS, 'id': T + 'carol', 'steps': None,
                    'optional': True},
    }])
    self.assertEqual(
        dict((r['name'], (r['a:reach']['steps'],
                          r['b:reach'] and r['b:reach']['steps']))
             for r in result),
        {'Alice': (3, 1), 'Bob': (2, 2), 'Carol': (4, None),
         'Dave': (1, 3), 'Erin': (2, 2)})

  def testAsOfTime(self):
    self.assertIsNone(
        self.read({'id': T + 'alice',
                   'reach': {'step': KNOWS, 'id': T + 'frank'}},
                  as_of_time='2000-01-01'))

  def testGraphQuery(self):
    gql = self.mql.high_querier.to_gql(
        None,
        {'id': T + 'alice',
         'reach': {'step|=': [KNOWS, '!' + KNOWS], 'id': T + 'carol',
                   'steps<=': 4, 'steps': None,
                   'paths': [{'path': [{'id': None}], 'limit': 3}]}}, {})
    self.assertIn('(<-path step=(', gql)
    self.assertIn('right->(*)', gql)
    self.assertIn('left->(*)', gql)
    self.assertIn('} | {', gql)
    self.assertIn('steps<=4 pathlimit=3 ', gql)
    self.assertIn('result=((steps (path) ))', gql)

  def assertParseError(self, reach, message):
    with self.assertRaisesRegex(error.MQLParseError, message):
      self.read({'id': T + 'alice', 'reach': reach})

  def testErrors(self):
    self.assertParseError({'id': T + 'frank'}, "needs a 'step'")
    self.assertParseError({'step': KNOWS, 'step|=': [KNOWS]},
                          "one of 'step' and 'step|='")
    self.assertParseError({'step': {KNOWS: {'name': None}}},
                          'exactly one "\\*"')
    self.assertParseError({'step': {KNOWS: {KNOWS: '*', 'name': '*'}}},
                          'exactly one "\\*"')
    self.assertParseError({'step': {'name': '*'}},
                          'values are objects')
    self.assertParseError({'step': {KNOWS: ['*']}}, "can't be in a list")
    self.assertParseError(
        {'step': {KNOWS: {'reach': {'step': KNOWS}, KNOWS: '*'}}},
        "'reach' inside a step")
    self.assertParseError({'step': {KNOWS: '*', 'return': 'count'}},
                          "'return' in a step")
    self.assertParseError({'step': KNOWS, 'path': {'name': None}},
                          "'path' must be")
    self.assertParseError({'step': KNOWS, 'path': [{'via': 1}]},
                          "'via' must be null")
    self.assertParseError({'step': KNOWS, 'paths': [{'limit': 3}]},
                          "'paths' must be")
    self.assertParseError({'step': KNOWS, 'steps<=': -1},
                          'non-negative integer')
    self.assertParseError({'step': KNOWS, 'return': 'steps'}, "'return'")
    self.assertParseError('frank', "'reach' must be")
    with self.assertRaisesRegex(error.MQLParseError, 'only in an object'):
      self.read({'id': T + 'alice', 'name': {'reach': {'step': KNOWS}}})
    with self.assertRaisesRegex(error.MQLParseError, 'only in a read'):
      self.write({'id': T + 'alice', 'reach': {'step': KNOWS}})


if __name__ == '__main__':
  absltest.main()
