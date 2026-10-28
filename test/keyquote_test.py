# -*- coding: utf-8 -*-
"""Unit tests for util/keyquote.py: namespace key quoting."""

from pymql.mql import error
from pymql.util import keyquote

from absl.testing import absltest


class KeyQuoteTest(absltest.TestCase):

  def testPlainKeysAreUnchanged(self):
    for key in ['abc', 'a_b', '_', 'A9', 'a-b', 'a--b']:
      self.assertEqual(keyquote.quotekey(key), key)

  def testHyphenOnlyInTheInterior(self):
    self.assertEqual(keyquote.quotekey('-ab'), '$002Dab')
    self.assertEqual(keyquote.quotekey('ab-'), 'ab$002D')
    self.assertEqual(keyquote.quotekey('-'), '$002D')

  def testEscapes(self):
    self.assertEqual(keyquote.quotekey('a b'), 'a$0020b')
    self.assertEqual(keyquote.quotekey('rss+xml'), 'rss$002Bxml')
    self.assertEqual(keyquote.quotekey('a.b'), 'a$002Eb')
    self.assertEqual(keyquote.quotekey(u'caf\xe9'), 'caf$00E9')

  def testUtf8BytesAreDecoded(self):
    self.assertEqual(keyquote.quotekey(b'caf\xc3\xa9'), 'caf$00E9')

  def testBeyondBmpIsASurrogatePair(self):
    # Python 2's narrow unicode builds produced these, and existing
    # Freebase keys use them.
    self.assertEqual(keyquote.quotekey(u'\U0001F600x'), '$D83D$DE00x')
    self.assertEqual(keyquote.unquotekey('$D83D$DE00x'), u'\U0001F600x')

  def testEmpty(self):
    self.assertEqual(keyquote.quotekey(''), '')
    self.assertEqual(keyquote.unquotekey(''), '')

  def testRejectsNonStrings(self):
    with self.assertRaises(ValueError):
      keyquote.quotekey(5)

  def testRoundTrip(self):
    for s in ['abc', '-ab', 'ab-', 'a b', 'rss+xml', u'caf\xe9', u'\u2603',
              u'\U0001F600', u'\U0001F600\U0001F601', '$', '1', 'a/b']:
      self.assertEqual(
          keyquote.unquotekey(keyquote.quotekey(s)), s, repr(s))

  def testUnquoteWithEncoding(self):
    self.assertEqual(keyquote.unquotekey('caf$00E9', 'utf-8'), b'caf\xc3\xa9')

  def testUnquoteRejectsInvalidKeys(self):
    for bad in ['a b', '-x', '$12', 'a.b']:
      with self.assertRaises(error.MQLInternalError, msg=bad):
        keyquote.unquotekey(bad)

  def testUnquoteId(self):
    self.assertEqual(
        keyquote.unquote_id('/media_type/application/rss$002Bxml'),
        '/media_type/application/rss+xml')
    self.assertEqual(keyquote.unquote_id('caf$00E9'), u'caf\xe9')


if __name__ == '__main__':
  absltest.main()
