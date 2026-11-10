"""A small co-author graph for the "reach" (path search) tests.

load(mql) writes it into a freshly bootstrapped graph:

  In the namespace /en/pt (NS): person, with person/knows (to a person),
  and reviewer, a second type some people have; paper, with paper/author.
  Each person and paper has a key in NS: /en/pt/alice, /en/pt/one.

  Papers and their authors:

    one    alice bob          five   alice erin
    two    bob carol          six    erin dave
    three  bob carol          seven  erin carol
    four   carol dave

  Everyone but erin is a reviewer; frank has no papers.
  knows: alice -> bob -> carol -> dave.

So, co-author by co-author: alice to carol is 2 steps two ways (through bob,
on papers one and two or three; through erin, on five and seven); alice to
dave is 2 steps through erin, or 3 through reviewers only (bob, carol).
"""

USER = {'$user': '/user/metaweb'}
NS = '/en/pt'

PEOPLE = ['alice', 'bob', 'carol', 'dave', 'erin', 'frank']
REVIEWERS = ['alice', 'bob', 'carol', 'dave', 'frank']
PAPERS = [
    ('one', ['alice', 'bob']),
    ('two', ['bob', 'carol']),
    ('three', ['bob', 'carol']),
    ('four', ['carol', 'dave']),
    ('five', ['alice', 'erin']),
    ('six', ['erin', 'dave']),
    ('seven', ['erin', 'carol']),
]
KNOWS = [('alice', 'bob'), ('bob', 'carol'), ('carol', 'dave')]


def load(mql):

  def write(query):
    return mql.write(query, **USER).result

  def key(namespace, value):
    return {'namespace': namespace, 'value': value}

  write({'create': 'unless_exists', 'id': None, 'type': '/type/namespace',
         'key': key('/en', 'pt')})

  for type_key, name in [('person', 'Person'), ('reviewer', 'Reviewer'),
                         ('paper', 'Paper')]:
    write({'create': 'unless_exists', 'id': None, 'type': '/type/type',
           'name': name, 'key': key(NS, type_key)})

  for schema, prop, expected, unique in [('person', 'knows', 'person', False),
                                         ('paper', 'author', 'person', False)]:
    write({'create': 'unless_exists', 'id': None, 'type': '/type/property',
           'name': prop, 'key': key(NS + '/' + schema, prop),
           'schema': {'connect': 'insert', 'id': NS + '/' + schema},
           'expected_type': {'connect': 'insert', 'id': NS + '/' + expected},
           'unique': unique})

  for person in PEOPLE:
    types = [NS + '/person']
    if person in REVIEWERS:
      types.append(NS + '/reviewer')
    write({'create': 'unless_exists', 'id': None, 'type': types,
           'name': person.capitalize(), 'key': key(NS, person)})

  for paper, authors in PAPERS:
    write({'create': 'unless_exists', 'id': None, 'type': NS + '/paper',
           'name': 'Paper ' + paper.capitalize(), 'key': key(NS, paper)})
    write({'id': NS + '/' + paper,
           NS + '/paper/author': [{'connect': 'insert', 'id': NS + '/' + a}
                                  for a in authors]})

  for a, b in KNOWS:
    write({'id': NS + '/' + a,
           NS + '/person/knows': {'connect': 'insert', 'id': NS + '/' + b}})
