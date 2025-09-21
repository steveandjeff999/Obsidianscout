import os
import re

ROOT = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(ROOT, 'app', 'templates')
VENDOR_CSS = [
    os.path.join(ROOT, 'app', 'static', 'css', 'vendor', 'fontawesome-all.min.css'),
    os.path.join(ROOT, 'app', 'static', 'css', 'vendor', 'select2-bootstrap-5-theme.min.css'),
]


def test_templates_no_external_assets():
    """Fail if any template includes external http(s) links for scripts or styles."""
    pattern = re.compile(r"<(?:script|link)[^>]+(?:href|src)=\"https?://", re.I)
    bad = []
    for root, _, files in os.walk(TEMPLATES_DIR):
        for f in files:
            if not f.endswith('.html'):
                continue
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as fh:
                txt = fh.read()
            if pattern.search(txt):
                bad.append(path)
    assert not bad, f'Templates with external assets found: {bad}'


def test_vendor_css_files_exist_and_not_placeholder():
    """Ensure key vendor CSS files exist and are above a small size threshold."""
    missing = []
    too_small = []
    for p in VENDOR_CSS:
        if not os.path.exists(p):
            missing.append(p)
            continue
        size = os.path.getsize(p)
        # 10 KB threshold to catch placeholder/minimal files
        if size < 10 * 1024:
            too_small.append((p, size))

    assert not missing, f'Missing vendor CSS files: {missing}'
    assert not too_small, f'Vendor CSS files too small (likely placeholders): {too_small}'
