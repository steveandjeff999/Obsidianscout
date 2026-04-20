from uuid import uuid4

from app import create_app, db
from app.models import Event, Team
from app.routes.teams import _ensure_team_associated_with_event_for_scope


def _new_event(code_suffix, scouting_team_number):
    code = f"2099{code_suffix}{uuid4().hex[:6].upper()}"
    evt = Event(
        name=f"Event {code}",
        code=code,
        year=2099,
        scouting_team_number=scouting_team_number,
    )
    db.session.add(evt)
    db.session.commit()
    return evt


def test_ensure_association_allows_same_team_number_cross_scope():
    app = create_app()
    with app.app_context():
        event = _new_event("XSC", scouting_team_number=3001)

        foreign = Team(team_number=990001, team_name="Foreign Team", scouting_team_number=4001)
        local = Team(team_number=990001, team_name="Local Team", scouting_team_number=3001)
        db.session.add(foreign)
        db.session.add(local)
        db.session.flush()

        foreign.events.append(event)
        db.session.commit()

        linked_now, already_linked, canonical = _ensure_team_associated_with_event_for_scope(
            local,
            event,
            scouting_team_number=3001,
        )
        db.session.commit()

        assert linked_now is True
        assert already_linked is False
        assert canonical.id == local.id
        assert event in local.events
        assert event in foreign.events


def test_ensure_association_prefers_existing_same_scope_linked_row():
    app = create_app()
    with app.app_context():
        event = _new_event("YSC", scouting_team_number=3002)

        already_linked = Team(team_number=990002, team_name="Canonical", scouting_team_number=3002)
        duplicate = Team(team_number=990002, team_name="Duplicate", scouting_team_number=3002)
        db.session.add(already_linked)
        db.session.add(duplicate)
        db.session.flush()

        already_linked.events.append(event)
        db.session.commit()

        linked_now, was_already_linked, canonical = _ensure_team_associated_with_event_for_scope(
            duplicate,
            event,
            scouting_team_number=3002,
        )
        db.session.commit()

        assert linked_now is False
        assert was_already_linked is True
        assert canonical.id == already_linked.id
        assert event in already_linked.events
        assert event not in duplicate.events
