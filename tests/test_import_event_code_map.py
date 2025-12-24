def test_import_maps_event_by_code_when_local_event_exists(tmp_path):
    from app import db
    from app.models import Event, AllianceSelection
    import app.routes.data as data_mod

    # Prepare helper to build zip bytes
    import zipfile, json
    from io import BytesIO
    def _make_zip_bytes(file_map):
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for name, data in file_map.items():
                z.writestr(name, json.dumps(data))
        buf.seek(0)
        return buf.read()

    # Create a local event that should be matched by code
    ev = Event(name='Existing Event', code='BND', year=2025)
    db.session.add(ev)
    db.session.commit()

    # Bundle references an exported event id 5 with the same code 'BND'
    files = {
        'events.json': [{"id": 5, "name": "Bundle Event", "code": "BND", "year": 2025}],
        'alliances.json': [{"id": 1, "alliance_number": 1, "captain": None, "first_pick": None, "second_pick": None, "third_pick": None, "event_id": 5, "timestamp": "2025-12-19T00:00:00", "scouting_team_number": None}]
    }
    zip_bytes = _make_zip_bytes(files)
    zpath = tmp_path / 'code_map.zip'
    zpath.write_bytes(zip_bytes)

    orig_app = data_mod.current_app
    try:
        # Use a dummy logger app to avoid app context requirement
        class DummyLogger:
            def info(self, *a, **k): pass
            def error(self, *a, **k): pass
            def exception(self, *a, **k): pass
        class DummyApp:
            def __init__(self):
                self.logger = DummyLogger()
        data_mod.current_app = DummyApp()

        success, msg = data_mod.import_portable_from_zip(str(zpath))
    finally:
        data_mod.current_app = orig_app

    assert success, msg
    imported_alliance = AllianceSelection.query.filter_by(alliance_number=1).first()
    assert imported_alliance is not None
    assert imported_alliance.event_id == ev.id
