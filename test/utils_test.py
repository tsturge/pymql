# -*- coding: utf-8 -*-
"""Unit tests for helpers in mql/utils.py."""

from pymql.mql import error
from pymql.mql import utils

from absl.testing import absltest


class CursorTest(absltest.TestCase):

  def testRoundTrip(self):
    for cursor in ['grcursor:abc', u'caf\xe9', '']:
      encoded = utils.encode_cursor(cursor)
      self.assertIsInstance(encoded, str)
      self.assertEqual(utils.decode_cursor(encoded), cursor)

  def testEncodedCursorIsUrlSafe(self):
    encoded = utils.encode_cursor('x' * 200 + '\xff\xfe')
    self.assertRegex(encoded, r'^[A-Za-z0-9_=-]+$')

  def testBooleansPassThrough(self):
    self.assertIs(utils.encode_cursor(True), True)
    self.assertIs(utils.decode_cursor(True), True)
    self.assertIs(utils.decode_cursor(False), False)

  def testInvalidCursors(self):
    for bad in ['not base64!', 'aGVsbG8=', u'caf\xe9']:
      with self.assertRaises(error.MQLParseError, msg=bad):
        utils.decode_cursor(bad)
    with self.assertRaises(error.MQLParseError):
      utils.decode_cursor(5)


class ValidatorTest(absltest.TestCase):

  def testValidTimestamp(self):
    for ts in ['2006', '2006-06', '2006-06-06T17:26:50.123',
               '2006-06-06T17:26:50.1234Z']:
      self.assertTrue(utils.valid_timestamp(ts), ts)
    for ts in ['1969', '2100', '20060', '2006-6', 'yesterday']:
      self.assertFalse(utils.valid_timestamp(ts), ts)

  def testValidGuidAndMid(self):
    self.assertTrue(utils.valid_guid('#' + '0' * 32))
    self.assertFalse(utils.valid_guid('0' * 32))
    self.assertFalse(utils.valid_guid('#' + '0' * 31))
    self.assertTrue(utils.valid_mid('/m/0bcd_9'))
    self.assertFalse(utils.valid_mid('/m/0aeiou'))

  def testValidKey(self):
    for key in ['a', 'a-b', 'a_b', 'rss$002Bxml', '$002Dab']:
      self.assertTrue(utils.valid_key(key), key)
    for key in ['-ab', 'ab-', 'a b', 'a/b', 'rss$002bxml', '']:
      self.assertFalse(utils.valid_key(key), key)

  def testValidIdname(self):
    for idname in ['/', '/a', '/a/b-c']:
      self.assertTrue(utils.valid_idname(idname), idname)
    for idname in ['a/b', '/a/', '//a', '']:
      self.assertFalse(utils.valid_idname(idname), idname)

  def testValidRelname(self):
    for rel in ['name', '/type/object/name', '!name', 'a:name', '+name', '*',
                '#' + 'f' * 32]:
      self.assertTrue(utils.valid_relname(rel), rel)
    for rel in ['a b', 'name:', '/type/']:
      self.assertFalse(utils.valid_relname(rel), rel)

  def testReservedWord(self):
    self.assertTrue(utils.reserved_word('sort'))
    self.assertTrue(utils.reserved_word('name'))
    self.assertFalse(utils.reserved_word('name', allow_type=True))
    self.assertFalse(utils.reserved_word('album'))


class KeyCompareTest(absltest.TestCase):

  def testKeyCompare(self):
    self.assertTrue(utils.key_compare('name', 'name'))
    self.assertTrue(utils.key_compare('a:name', 'a:name'))
    self.assertTrue(utils.key_compare('name', 'a:name'))
    self.assertFalse(utils.key_compare('a:name', 'name'))
    self.assertFalse(utils.key_compare('a:name', 'b:name'))
    self.assertFalse(utils.key_compare('!name', 'name'))
    self.assertFalse(utils.key_compare('/type/object/name', 'name'))

  def testFindKeyInQuery(self):
    query = {'a:name': None, 'type': '/music/artist'}
    self.assertEqual(utils.find_key_in_query('name', query), 'a:name')
    self.assertIsNone(utils.find_key_in_query('id', query))


class MiscTest(absltest.TestCase):

  def testParseTildeOp(self):
    self.assertEqual(
        utils.parse_tilde_op('I "Love You" Fred'), ['I', 'Love You', 'Fred'])
    self.assertEqual(utils.parse_tilde_op('one'), ['one'])

  def testIdLength(self):
    self.assertEqual(utils.id_length('/'), 0)
    self.assertEqual(utils.id_length('/a'), 1)
    self.assertEqual(utils.id_length('/a/b'), 2)

  def testMakeComparisonTruekey(self):
    self.assertEqual(utils.make_comparison_truekey(None, None, 'name'), 'name')
    self.assertEqual(utils.make_comparison_truekey('!', None, 'name'), '!name')
    self.assertEqual(utils.make_comparison_truekey(None, 'a', 'name'), 'a:name')
    self.assertEqual(
        utils.make_comparison_truekey('!', 'a', 'name'), '!a:name')


if __name__ == '__main__':
  absltest.main()
