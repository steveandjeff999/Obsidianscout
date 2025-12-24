import json
import zipfile
from io import BytesIO
import tempfile
import os

import app.routes.data as data_mod

class DummyLogger:
    def info(self, *a, **k): pass
    def error(self, *a, **k): pass
    def exception(self, *a, **k): pass

class DummyApp:
    def __init__(self):
        self.logger = DummyLogger()


def _make_zip_bytes(file_map):
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in file_map.items():
            z.writestr(name, json.dumps(data))
    buf.seek(0)
    return buf.read()


def test_import_from_separate_files(tmp_path):
    # Prepare minimal JSON files inside a zip
    files = {
        'events.json': [{"id": 1, "name": "Test Event", "code": "TEST", "year": 2025}],
        'teams.json': [{"id": 1, "team_number": 111}],
        'matches.json': [{"id": 1, "match_number": 1}]
    }
    zip_bytes = _make_zip_bytes(files)
    zpath = tmp_path / 'portable.zip'
    zpath.write_bytes(zip_bytes)

    captured = {}

    orig_proc = data_mod._process_portable_data
    orig_app = data_mod.current_app
    try:
        data_mod.current_app = DummyApp()
        def fake_proc(export_data):
            captured.update(export_data)
            return True, 'ok'
        data_mod._process_portable_data = fake_proc
        success, msg = data_mod.import_portable_from_zip(str(zpath))
    finally:
        data_mod._process_portable_data = orig_proc
        data_mod.current_app = orig_app

    assert success
    assert 'events' in captured and len(captured['events']) == 1
    assert 'teams' in captured and len(captured['teams']) == 1


def test_import_from_bundle_file(tmp_path):
    bundle = {
        'events': [{"id": 99, "name": "Bundle Event", "code": "BND", "year": 2025}],
        'teams': [{"id": 88, "team_number": 888}]
    }
    zip_bytes = _make_zip_bytes({'export.json': bundle})
    zpath = tmp_path / 'bundle.zip'
    zpath.write_bytes(zip_bytes)

    captured = {}
    orig_proc = data_mod._process_portable_data
    orig_app = data_mod.current_app
    try:
        data_mod.current_app = DummyApp()
        def fake_proc(export_data):
            captured.update(export_data)
            return True, 'ok'
        data_mod._process_portable_data = fake_proc
        success, msg = data_mod.import_portable_from_zip(str(zpath))
    finally:
        data_mod._process_portable_data = orig_proc
        data_mod.current_app = orig_app

    assert success
    assert 'events' in captured and len(captured['events']) == 1
    assert captured['events'][0]['id'] == 99
    assert 'teams' in captured and len(captured['teams']) == 1
