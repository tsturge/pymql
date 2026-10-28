# -*- coding: utf-8 -*-
"""Unit tests for mql/grquoting.py: graphd string quoting and escaping."""

from pymql.error import FormattingError
from pymql.mql import grquoting

from absl.testing import absltest


class QuoteTest(absltest.TestCase):

  def testQuote(self):
    self.assertEqual(grquoting.quote('abc'), '"abc"')
    self.assertEqual(grquoting.quote(''), '""')
    self.assertEqual(grquoting.quote('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')

  def testOnlyQuoteBackslashAndNewlineAreEscaped(self):
    self.assertEqual(grquoting.quote('\t\r'), '"\t\r"')

  def testUnquote(self):
    self.assertEqual(grquoting.unquote('"abc"'), 'abc')
    self.assertEqual(grquoting.unquote('""'), '')
    self.assertEqual(grquoting.unquote('"a\\"b\\\\c\\nd"'), 'a"b\\c\nd')

  def testRoundTrip(self):
    for s in ['', 'plain', '"', '\\', '\n', 'a\\"b', u'caf\xe9',
              u'\u2603', u'\U0001F600', '\\n', 'trailing\\']:
      self.assertEqual(grquoting.unquote(grquoting.quote(s)), s, repr(s))

  def testUnquoteRejectsBadStrings(self):
    for bad in ['abc', '"abc', 'abc"', '"a"b"', '"a\\tb"', '"a\\"', '']:
      with self.assertRaises(FormattingError, msg=repr(bad)):
        grquoting.unquote(bad)


class EscapeTest(absltest.TestCase):

  def testEscapeMarkup(self):
    self.assertEqual(grquoting.escapeMarkup('<a & b>"\''), '&lt;a &amp; b&gt;"\'')

  def testEscapeAttribute(self):
    self.assertEqual(grquoting.escapeAttribute('x"y'), '\'x"y\'')
    self.assertEqual(grquoting.escapeAttribute('x\'"y'), '"x\'&quot;y"')

  def testEscapeUrl(self):
    self.assertEqual(grquoting.escapeUrl('a b/c'), 'a%20b/c')
    self.assertEqual(grquoting.escapeUrl(u'caf\xe9'), 'caf%C3%A9')


if __name__ == '__main__':
  absltest.main()
