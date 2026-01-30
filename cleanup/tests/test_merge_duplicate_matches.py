import unittest
from app import create_app, db
from app.models import Event, Match, ScoutingData
from app.routes.data import merge_duplicate_matches
from datetime import datetime, timezone

class MergeDuplicateMatchesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_merge_simple_duplicates(self):
        # Create an event
        ev = Event(name='Test Event', code='TEST', year=2026)
        db.session.add(ev)
        db.session.flush()

        # Create duplicate matches (same event_id, match_number, match_type)
        m1 = Match(match_number=1, match_type='Playoff', event_id=ev.id, red_alliance='111,222', blue_alliance='', red_score=None, blue_score=None)
        m2 = Match(match_number=1, match_type='Playoff', event_id=ev.id, red_alliance='', blue_alliance='333,444', red_score=10, blue_score=20, winner='blue')
        db.session.add(m1)
        db.session.add(m2)
        db.session.flush()

        # Add scouting data to the duplicate to ensure it moves
        sd = ScoutingData(match_id=m2.id, team_id=1, scouting_team_number=None, scout_name='tester', scouting_station=1, data_json='{}')
        db.session.add(sd)
        db.session.commit()

        # Run merge
        deleted = merge_duplicate_matches()
        self.assertEqual(deleted, 1)

        # Check keep match has combined alliances and scores
        kept = Match.query.filter_by(event_id=ev.id, match_number=1, match_type='Playoff').first()
        self.assertIsNotNone(kept)
        self.assertIn('111', kept.red_alliance)
        self.assertIn('333', kept.blue_alliance)
        self.assertEqual(kept.red_score, 10)
        self.assertEqual(kept.blue_score, 20)

        # Scouting data should now be attached to kept match
        sd2 = ScoutingData.query.filter_by(match_id=kept.id).first()
        self.assertIsNotNone(sd2)

if __name__ == '__main__':
    unittest.main()
