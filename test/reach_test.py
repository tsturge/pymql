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

  def testMoreErrors(self):
    self.assertParseError({'step|=': []}, "'step\\|=' must be a list")
    self.assertParseError({'step': 5}, 'A step must be a property')
    self.assertParseError({'step': 'name'}, 'values are objects')
    self.assertParseError({'step': '!!' + KNOWS}, 'not a valid property')
    self.assertParseError({'step': {}}, 'must name a property')
    self.assertParseError({'step': KNOWS, 'steps': 'three'},
                          'non-negative integer')
    self.assertParseError({'step': KNOWS, 'steps>=': True},
                          'non-negative integer')
    self.assertParseError({'step': KNOWS, 'path': [{'limit': 1}]},
                          "Can't use 'limit' in the objects on a path")
    self.assertParseError(
        {'step': KNOWS, 'path': [{'reach': {'step': KNOWS}}]},
        "Can't use 'reach' in the objects on a path")
    self.assertParseError(
        {'step': KNOWS, 'paths': [{'path': [{}], 'limit': 0}]},
        'positive integer')
    self.assertParseError({'step': KNOWS, 'paths': {'return': 'name'}},
                          "'paths' must be")
    self.assertParseError([{'step': KNOWS}, {'step': KNOWS}],
                          "'reach' must be")
    with self.assertRaises(error.MQLTypeError):
      self.read({'id': T + 'alice',
                 'reach': {'step': PERSON + '/no_such_property'}})

  def testTargetPattern(self):
    # the target is any subquery, not only an id
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name': 'Frank', 'id': None,
                              'steps': None}]),
        [{'name': 'Frank', 'id': T + 'frank', 'steps': 3}])
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name~=': 'Da*',
                              'name': None}]),
        [{'name': 'Dave'}])
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'type': PERSON,
                              'knows': 'Frank', 'name': None}]),
        [{'type': PERSON, 'knows': 'Frank', 'name': 'Dave'}])
    self.assertIsNone(
        self.read({'id': T + 'alice',
                   'reach': {'step': KNOWS, 'id': T + 'nobody'}}))

  def testStepsComparisons(self):
    def names(**comparison):
      return self.reach('alice', [dict({'step': KNOWS, 'return': 'name',
                                        'name': None}, **comparison)])
    self.assertEqual(names(**{'steps>=': 2}), ['Dave', 'Frank'])
    self.assertEqual(names(**{'steps>': 2}), ['Frank'])
    self.assertEqual(names(**{'steps<': 2}), ['Bob', 'Erin'])
    # no match: the start doesn't match either, unless it is optional
    self.assertIsNone(
        self.read({'id': T + 'alice',
                   'reach': [{'step': KNOWS, 'steps>': 3}]}))
    self.assertEqual(names(**{'steps>': 3, 'optional': True}), [])

  def testSortAndCount(self):
    self.assertEqual(
        self.reach('alice', [{'step': KNOWS, 'name': None,
                              'sort': '-name', 'return': 'name'}]),
        ['Frank', 'Erin', 'Dave', 'Bob'])
    result = self.reach('alice', [{'step': KNOWS, 'name': None,
                                   'count': None}])
    self.assertEqual([r['count'] for r in result], [4, 4, 4, 4])

  def testForbidden(self):
    # those of the six who can't reach frank (testAsOfTimeBetweenWrites
    # adds more people)
    six = ['Alice', 'Bob', 'Carol', 'Dave', 'Erin', 'Frank']
    result = self.read([{'type': PERSON, 'name': None, 'name|=': six,
                         'reach': {'step': KNOWS, 'id': T + 'frank',
                                   'optional': 'forbidden'}}])
    self.assertEqual([r['name'] for r in result], ['Frank'])

  def testAnyLinkEitherWay(self):
    # the reflection properties follow every link: alice and frank are
    # two steps apart through their type, their namespace and more
    result = self.reach(
        'alice', {'step|=': ['/type/reflect/any_master',
                             '/type/reflect/any_reverse'],
                  'id': T + 'frank', 'steps': None})
    self.assertEqual(result['steps'], 2)
    result = self.reach(
        'alice', {'step|=': ['/type/reflect/any_master',
                             '/type/reflect/any_reverse'],
                  'id': T + 'carol', 'steps': None,
                  'path': [{'id': None, 'via': None}]})
    self.assertEqual(result['steps'], 1)
    self.assertEqual(result['path'][1],
                     {'id': T + 'carol',
                      'via': {'/type/reflect/any_reverse': '*'}})

  def testStepRootFields(self):
    # fields at a step's root are those of the object the step leaves
    result = self.reach('alice', {'step': {'name': None, KNOWS: '*'},
                                  'id': T + 'dave',
                                  'path': [{'via': None}]})
    self.assertEqual(result['path'], [
        {},
        {'via': {'name': 'Alice', KNOWS: '*'}},
        {'via': {'name': 'Bob', KNOWS: '*'}},
    ])

  def testConstraintInStep(self):
    # a given value in a step constrains which steps there are
    step = {KNOWS: [{'name': 'Bob', KNOWS: '*'}]}
    result = self.reach('alice', {'step': step, 'id': T + 'dave',
                                  'path': [{'via': None}]})
    self.assertEqual(result['path'][1],
                     {'via': {KNOWS: [{'name': 'Bob', KNOWS: '*'}]}})
    step = {KNOWS: {'name': 'Carol', KNOWS: '*'}}
    self.assertIsNone(
        self.read({'id': T + 'alice',
                   'reach': {'step': step, 'id': T + 'dave'}}))

  def testOptionalSubqueryInStep(self):
    # an optional subquery only returns values: read after the search
    step = {KNOWS: '*', 'b:' + KNOWS: [{'name': None, 'optional': True}]}
    query = {'id': T + 'alice',
             'reach': {'step': step, 'id': T + 'bob',
                       'path': [{'via': None}]}}
    self.assertNotIn('optional',
                     self.mql.high_querier.to_gql(None, query, {}))
    self.assertEqual(
        self.read(query)['reach']['path'][1]['via'],
        {KNOWS: '*', 'b:' + KNOWS: [{'name': 'Bob'}, {'name': 'Erin'}]})

  def testReachInASubquery(self):
    # from carol's friend; "knows" is looked up on the friend's type
    result = self.read({
        'id': T + 'carol', 'type': PERSON,
        'knows': {'name': None,
                  'reach': {'step': 'knows', 'id': T + 'frank',
                            'steps': None}}})
    self.assertEqual(result['knows'],
                     {'name': 'Alice',
                      'reach': {'id': T + 'frank', 'steps': 3}})

  def testPathsWithVia(self):
    result = self.reach('alice', {
        'step|=': [KNOWS, '!' + KNOWS], 'id': T + 'frank',
        'paths': [{'path': [{'name': None, 'via': None}]}]})
    self.assertEqual(result['paths'], [
        {'path': [{'name': 'Alice'},
                  {'name': name, 'via': {KNOWS: '*'}},
                  {'name': 'Dave', 'via': {KNOWS: '*'}},
                  {'name': 'Frank', 'via': {KNOWS: '*'}}]}
        for name in ('Bob', 'Erin')
    ])

  def testPathsForManyStarts(self):
    # one read fills the objects on every start's path
    result = self.read([{
        'type': PERSON, 'name': None, 'sort': 'name',
        'reach': {'step': KNOWS, 'id': T + 'frank', 'return': 'path',
                  'path': [{'name': None}]}}])
    self.assertEqual(
        dict((r['name'], [n['name'] for n in r['reach']]) for r in result),
        {'Alice': ['Alice', 'Bob', 'Dave', 'Frank'],
         'Bob': ['Bob', 'Dave', 'Frank'],
         'Carol': ['Carol', 'Alice', 'Bob', 'Dave', 'Frank'],
         'Dave': ['Dave', 'Frank'],
         'Erin': ['Erin', 'Dave', 'Frank']})

  def testReturnPath(self):
    self.assertEqual(
        self.reach('alice', {'step': KNOWS, 'id': T + 'dave',
                             'path': [{'name': None}], 'return': 'path'}),
        [{'name': 'Alice'}, {'name': 'Bob'}, {'name': 'Dave'}])
    self.assertEqual(
        self.reach('alice', {'step': KNOWS, 'id': T + 'frank',
                             'paths': {'return': 'count'},
                             'return': 'paths'}), 2)

  def testAsOfTimeBetweenWrites(self):
    # gina -> hank, then hank -> ivan: as of the first, no path to ivan
    for name in ('gina', 'hank', 'ivan'):
      self.write({'create': 'unless_exists', 'id': None, 'type': PERSON,
                  'name': name.capitalize(),
                  'key': {'namespace': '/en/test', 'value': name}})
    self.write({'id': T + 'gina', 'type': PERSON,
                'knows': {'connect': 'insert', 'id': T + 'hank'}})
    first = self.read({'id': T + 'gina', 'type': PERSON,
                       'knows': {'id': T + 'hank',
                                 'link': {'timestamp': None}}})
    first = first['knows']['link']['timestamp']
    self.write({'id': T + 'hank', 'type': PERSON,
                'knows': {'connect': 'insert', 'id': T + 'ivan'}})

    query = {'id': T + 'gina',
             'reach': {'step': KNOWS, 'id': T + 'ivan', 'steps': None}}
    self.assertEqual(self.read(query)['reach']['steps'], 2)
    self.assertIsNone(self.read(query, as_of_time=first))
    query['reach']['id'] = T + 'hank'
    self.assertEqual(self.read(query, as_of_time=first)['reach']['steps'], 1)


if __name__ == '__main__':
  absltest.main()
