import unittest

from app.utils.api_utils import _merge_match_lists


class TestMergePlayoffMatches(unittest.TestCase):
    def test_merge_tba_and_first_playoff(self):
        # TBA-style match (semifinals set 1, match 1)
        tba = {
            'match_number': 1,
            'display_match_number': '1-1',
            'match_type': 'Playoff',
            'comp_level': 'sf',
            'set_number': 1,
            'raw_match_number': 1,
            'red_alliance': '254,111,222',
            'blue_alliance': '',
            'red_score': None,
            'blue_score': None,
            'winner': None
        }

        # FIRST-style match for the same semifinal (has teams on blue side and scores)
        first = {
            'match_number': 1,
            'display_match_number': '1',
            'match_type': 'Playoff',
            'comp_level': 'sf',
            'set_number': 1,
            'raw_match_number': 1,
            'red_alliance': '',
            'blue_alliance': '333,444,555',
            'red_score': 10,
            'blue_score': 20,
            'winner': 'blue'
        }

        merged = _merge_match_lists([tba], [first])
        self.assertEqual(len(merged), 1)
        m = merged[0]
        # Both alliances should be present after merge
        self.assertIn('254', m['red_alliance'])
        self.assertIn('333', m['blue_alliance'])
        # Scores and winner should be from FIRST data
        self.assertEqual(m['red_score'], 10)
        self.assertEqual(m['blue_score'], 20)
        self.assertEqual(m['winner'], 'blue')


if __name__ == '__main__':
    unittest.main()
