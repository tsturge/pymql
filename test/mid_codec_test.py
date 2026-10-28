# -*- coding: utf-8 -*-
"""Unit tests for mql/mid.py: converting between guids and /m/ mids.

mids_test.py covers mids in MQL queries; this tests the codec itself.
"""

from pymql.mql import mid

from absl.testing import absltest

GRAPH0 = '9202a8c04000641f8'


class MidTest(absltest.TestCase):

  def testKnownMid(self):
    guid = '9202a8c04000641f80000000013e068e'
    self.assertEqual(mid.of_guid(guid), '/m/0mx1ng')
    self.assertEqual(mid.to_guid('/m/0mx1ng'), guid)

  def testSmallestAndLargestObjectIds(self):
    self.assertEqual(mid.of_guid(GRAPH0 + '000000000000000'), '/m/0')
    self.assertEqual(mid.of_guid(GRAPH0 + '000000000000001'), '/m/01')
    self.assertEqual(mid.of_guid(GRAPH0 + '0000003ffffffff'), '/m/0h______')

  def testRoundTrip(self):
    for objid in [0, 1, 31, 32, 0x13e068e, 0x3ffffffff]:
      guid = GRAPH0 + '%015x' % objid
      self.assertEqual(mid.to_guid(mid.of_guid(guid)), guid)

  def testGuidsOutsideTheMidGraphs(self):
    # The bootstrapped test graph's guids have no mids.
    with self.assertRaises(mid.UnknownGraphID):
      mid.of_guid('0000001240003456800000000000000a')

  def testInvalidMidCharacters(self):
    # Vowels aren't munch characters.
    with self.assertRaises(mid.InvalidMunch):
      mid.to_guid('/m/0aeiou')

  def testMunches(self):
    for n in range(32):
      self.assertEqual(mid.munch_of_char(mid.char_of_munch(n)), n)
    with self.assertRaises(mid.InvalidMunch):
      mid.char_of_munch(32)
    with self.assertRaises(mid.InvalidMunch):
      mid.munch_of_char('a')


if __name__ == '__main__':
  absltest.main()
