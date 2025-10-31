"""
Test Script: Schedule Adjustment Feature
Demonstrates how the schedule adjuster detects and corrects for event delays
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_schedule_adjustment():
    """Test the schedule adjustment functionality"""
    from app import create_app, db
    from app.models import Event, Match, User
    from app.utils.schedule_adjuster import update_event_schedule, ScheduleAdjuster
    from app.utils.config_manager import load_game_config
    
    app = create_app()
    
    with app.app_context():
        print("\n" + "="*70)
        print("SCHEDULE ADJUSTMENT TEST")
        print("="*70)
        
        # Get current event from game config
        try:
            # Try to get first user's scouting team number
            user = User.query.filter(User.scouting_team_number.isnot(None)).first()
            if not user:
                print(" No users with scouting team numbers found")
                return
            
            scouting_team_number = user.scouting_team_number
            print(f"\n Using scouting team: {scouting_team_number}")
            
            # Get their event
            game_config = load_game_config(team_number=scouting_team_number)
            event_code = game_config.get('current_event_code')
            
            if not event_code:
                print(" No current event configured")
                print(" Set current_event_code in app_config.json")
                return
            
            print(f" Event code: {event_code}")
            
            # Get event from database
            event = Event.query.filter_by(
                code=event_code,
                scouting_team_number=scouting_team_number
            ).first()
            
            if not event:
                print(f" Event {event_code} not found in database")
                print(" Sync matches first to create the event")
                return
            
            print(f" Event: {event.name}")
            print(f" Timezone: {event.timezone}")
            print(f" Current offset: {event.schedule_offset or 0} minutes")
            
            # Get match count
            match_count = Match.query.filter_by(event_id=event.id).count()
            print(f" Total matches: {match_count}")
            
            if match_count == 0:
                print("\n️  No matches found for this event")
                print(" Sync matches from the FRC API first")
                return
            
            print("\n" + "-"*70)
            print("ANALYZING SCHEDULE...")
            print("-"*70)
            
            # Run schedule analysis
            adjuster = ScheduleAdjuster(event, scouting_team_number)
            analysis = adjuster.analyze_schedule_variance()
            
            print(f"\n ANALYSIS RESULTS:")
            print(f"   Offset: {analysis['offset_minutes']:+.1f} minutes")
            print(f"   Recent offset: {analysis['recent_offset_minutes']:+.1f} minutes")
            print(f"   Confidence: {analysis['confidence']:.1%}")
            print(f"   Sample size: {analysis['sample_size']} completed matches")
            
            if analysis['sample_size'] == 0:
                print("\n️  No completed matches with actual times yet")
                print(" This is expected if:")
                print("   - Event hasn't started")
                print("   - TBA hasn't updated actual times yet")
                print("   - Event is brand new")
                print("\nThe schedule adjuster will work once matches start playing!")
                return
            
            # Determine schedule status
            offset = analysis['recent_offset_minutes']
            if abs(offset) < 2:
                status = " ON SCHEDULE"
                emoji = ""
            elif offset > 0:
                status = f"️  BEHIND SCHEDULE by {offset:.0f} minutes"
                emoji = ""
            else:
                status = f" AHEAD OF SCHEDULE by {abs(offset):.0f} minutes"
                emoji = ""
            
            print(f"\n{emoji} {status}")
            
            # Check if adjustment will be applied
            if analysis['confidence'] < 0.3:
                print(f"\n️  Confidence {analysis['confidence']:.1%} is below 30% threshold")
                print("   Schedule adjustment will NOT be applied yet")
                print("   More matches needed for reliable adjustment")
            elif abs(offset) < 5:
                print(f"\n Offset {offset:+.1f} min is minimal (< 5 min)")
                print("   No significant adjustment needed")
            else:
                print(f"\n Will adjust future match predictions")
                
                # Count future matches
                from datetime import datetime, timezone as tz
                now = datetime.now(tz.utc)
                future_count = Match.query.filter(
                    Match.event_id == event.id,
                    Match.scheduled_time > now
                ).count()
                
                print(f"   Future matches to adjust: {future_count}")
            
            print("\n" + "-"*70)
            print("TESTING FULL UPDATE...")
            print("-"*70)
            
            # Run full update (this will adjust and reschedule)
            result = update_event_schedule(
                event_code=event_code,
                scouting_team_number=scouting_team_number,
                reschedule_notifications=True
            )
            
            if result['success']:
                print(f"\n Schedule update completed!")
                print(f"   Matches adjusted: {result['adjusted_matches']}")
                print(f"   Notifications rescheduled: {result['rescheduled_notifications']}")
                
                # Reload event to see updated offset
                db.session.refresh(event)
                print(f"   Event offset updated to: {event.schedule_offset or 0} minutes")
                
                if result['should_notify_users']:
                    print(f"\n Significant schedule change detected!")
                    print(f"   Consider notifying users about the delay")
            else:
                print(f"\n Update failed: {result.get('error')}")
            
            print("\n" + "="*70)
            print("TEST COMPLETED")
            print("="*70)
            print("\nNext steps:")
            print("  1. The notification worker runs this automatically every 15 minutes")
            print("  2. Match predictions will be adjusted as events progress")
            print("  3. Notifications will be sent at the correct adjusted times")
            print("  4. Check console logs for schedule adjustment activity")
            
        except Exception as e:
            print(f"\n Error during test: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    test_schedule_adjustment()
