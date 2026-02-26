import json
import zipfile
from io import BytesIO

import pandas as pd
from app.models import Event, Match, QualitativeScoutingData


def _make_event_and_match(app):
    with app.app_context():
        e = Event(name="ExportTest", code="EXP", year=2025)
        from app import db
        db.session.add(e)
        db.session.flush()
        m = Match(match_number=1, match_type="Qualification", event_id=e.id)
        db.session.add(m)
        db.session.commit()
        return e, m


def test_export_portable_includes_qualitative(client, app):
    # create a qualitative entry so export has something to write
    with app.app_context():
        event, match = _make_event_and_match(app)
        q = QualitativeScoutingData(
            match_id=match.id,
            scouting_team_number=123,
            scout_name="tester",
            alliance_scouted="red",
            data_json=json.dumps({"key": "value"})
        )
        from app import db
        db.session.add(q)
        db.session.commit()

    resp = client.get('/data/export/portable')
    assert resp.status_code == 200
    buf = BytesIO(resp.data)
    z = zipfile.ZipFile(buf)
    assert 'qualitative_data.json' in z.namelist()
    qual = json.loads(z.read('qualitative_data.json'))
    assert len(qual) == 1
    assert qual[0].get('scout_name') == 'tester'


def test_export_excel_includes_qualitative(client, app):
    # reuse previous database state; may already include a qualitative entry
    resp = client.get('/data/export/excel?download=1')
    assert resp.status_code == 200
    buf = BytesIO(resp.data)
    xl = pd.ExcelFile(buf)
    # sheet name defined in export as 'Qualitative'
    assert 'Qualitative' in xl.sheet_names
    df = xl.parse('Qualitative')
    # core columns should be present
    assert 'scout_name' in df.columns
    assert 'alliance_scouted' in df.columns
    # if row exists, any nested keys should have produced data_* columns
    if not df.empty:
        # insert a nested structure entry and re-export to test
        with app.app_context():
            event, match = _make_event_and_match(app)
            q2 = QualitativeScoutingData(
                match_id=match.id,
                scouting_team_number=456,
                scout_name="nested",
                alliance_scouted="blue",
                data_json=json.dumps({
                    'red': {'team_111': {'notes': 'hi', 'rank': 1}},
                    'blue': {'team_222': {'notes': 'bye', 'rank': 2}}
                })
            )
            from app import db
            db.session.add(q2)
            db.session.commit()
        # export again
        resp2 = client.get('/data/export/excel?download=1')
        buf2 = BytesIO(resp2.data)
        xl2 = pd.ExcelFile(buf2)
        df2 = xl2.parse('Qualitative')
        # ensure flattened columns appear
        assert any(col.startswith('data_red_team_111_notes') for col in df2.columns)
        assert any(col.startswith('data_blue_team_222_rank') for col in df2.columns)
