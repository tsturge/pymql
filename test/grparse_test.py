# -*- coding: utf-8 -*-
"""Unit tests for mql/grparse.py, the graphd reply parser."""

from pymql.mql import error
from pymql.mql import grparse

from absl.testing import absltest


def parse(*chunks):
  """Feed chunks to a fresh parser; return it."""
  parser = grparse.ReplyParser()
  for chunk in chunks:
    parser.parsestr(chunk)
  return parser


class ReplyParserTest(absltest.TestCase):

  def testOkReply(self):
    reply = parse(b'ok (("a" 0123 null) ("b"))\n').get_reply()
    self.assertEqual(reply.status, 'ok')
    self.assertEqual(list(reply), [['"a"', '0123', 'null'], ['"b"']])
    self.assertIsNone(reply.cost)
    self.assertIsNone(reply.dateline)

  def testModifiers(self):
    reply = parse(b'ok id="q1" cost="tr=1 tu=2" dateline="12.3a" ()\n'
                 ).get_reply()
    self.assertEqual(reply.id, 'q1')
    self.assertEqual(reply.cost, 'tr=1 tu=2')
    self.assertEqual(reply.dateline, '12.3a')
    self.assertEqual(list(reply), [])

  def testBareOk(self):
    reply = parse(b'ok\n').get_reply()
    self.assertEqual(reply.status, 'ok')
    self.assertEqual(list(reply), [])

  def testBareOkWithModifier(self):
    reply = parse(b'ok dateline="12.3a"\n').get_reply()
    self.assertEqual(list(reply), [])
    self.assertEqual(reply.dateline, '12.3a')

  def testQuotedStringsKeepTheirEscapes(self):
    reply = parse(b'ok ("a\\"b\\\\c\\nd")\n').get_reply()
    self.assertEqual(list(reply), ['"a\\"b\\\\c\\nd"'])

  def testEmptyIsNotAnError(self):
    reply = parse(b'error EMPTY "not found"\n').get_reply()
    self.assertEqual(reply.status, 'error')
    self.assertEqual(reply.errcode, 'EMPTY')
    self.assertEqual(reply.errmsg, 'not found')
    self.assertEqual(list(reply), [])

  def testErrorCodes(self):
    cases = [
        ('BADCURSOR', error.MQLCursorInvalidError),
        ('DATELINE', error.MQLDatelineInvalidError),
        ('AGAIN', error.GraphIsSnapshottingError),
        ('COST', error.MQLTimeoutError),
        ('SEMANTICS', error.MQLGraphError),
        ('SYNTAX', error.MQLGraphError),
    ]
    for code, exc in cases:
      parser = parse(('error %s "oops"\n' % code).encode('ascii'))
      with self.assertRaises(exc, msg=code):
        parser.get_reply()

  def testUnknownStatus(self):
    with self.assertRaises(error.MQLGraphError):
      parse(b'huh ()\n').get_reply()

  def testUnknownModifier(self):
    with self.assertRaises(error.MQLGraphError):
      parse(b'ok bogus= "x" ()\n').get_reply()

  def testUnbalancedClose(self):
    with self.assertRaises(error.MQLGraphError):
      parse(b'ok (a))\n')

  def testUnbalancedOpen(self):
    with self.assertRaises(error.MQLGraphError):
      parse(b'ok ((a)\n')

  def testSeveralRepliesInOneChunk(self):
    parser = parse(b'ok (a)\nok (b)\n')
    self.assertEqual(list(parser.get_reply()), ['a'])
    self.assertEqual(list(parser.get_reply()), ['b'])
    self.assertFalse(parser.isready())

  def testReplySplitAcrossChunks(self):
    parser = parse(b'ok ("hel', b'lo" ', b'x)')
    self.assertFalse(parser.isready())
    parser.parsestr(b'\n')
    self.assertTrue(parser.isready())
    self.assertEqual(list(parser.get_reply()), ['"hello"', 'x'])

  def testMultibyteCharacterSplitAcrossChunks(self):
    # U+00E9 is C3 A9 in UTF-8; a socket read can end between them.
    parser = parse(b'ok ("caf\xc3', b'\xa9")\n')
    self.assertEqual(list(parser.get_reply()), [u'"caf\xe9"'])

  def testInvalidUtf8SurvivesAsSurrogates(self):
    reply = parse(b'ok ("\xff")\n').get_reply()
    self.assertEqual(list(reply), [u'"\udcff"'])
    self.assertEqual(reply[0].encode('utf-8', 'surrogateescape'), b'"\xff"')

  def testTextInput(self):
    # conn_mock feeds recorded replies as text.
    reply = parse(u'ok ("caf\xe9")\n').get_reply()
    self.assertEqual(list(reply), [u'"caf\xe9"'])


class HelpersTest(absltest.TestCase):

  def testCoststrToDict(self):
    self.assertEqual(
        grparse.coststr_to_dict('tr=12 tu=3 dw=0'),
        {'tr': 12, 'tu': 3, 'dw': 0})
    self.assertIsNone(grparse.coststr_to_dict(''))
    self.assertIsNone(grparse.coststr_to_dict(None))

  def testGstrUnescape(self):
    self.assertEqual(grparse.gstr_unescape('"a\\nb"'), 'a\nb')
    # Barewords such as datatypes pass through.
    self.assertEqual(grparse.gstr_unescape('boolean'), 'boolean')

  def testCostCodesAreDocumented(self):
    for code in ('tr', 'tu', 'ts', 'dr', 'dw', 'ir', 'iw', 'va', 'te'):
      self.assertIn(code, grparse.costcode_dict)


if __name__ == '__main__':
  absltest.main()
