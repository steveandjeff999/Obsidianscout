#!/usr/bin/env python3
"""
Fetch minified vendor JS/CSS libraries and save them into the project's
`app/static/js/vendor` and `app/static/css/vendor` directories.

Usage:
  python scripts/fetch_vendors.py [--force]

The script is idempotent and will skip files that already exist unless
`--force` is passed.

It will also parse downloaded CSS files for `url(...)` references (e.g.
webfonts used by Font Awesome) and download those assets into a
`webfonts/` subdirectory next to the CSS file, rewriting the CSS to
reference the local `webfonts/` files.
"""
from __future__ import annotations

import errno
import os
import re
import sys
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"

VENDORS = {
    # JS libraries
    "js/vendor/jquery-3.7.1.min.js": [
        "https://code.jquery.com/jquery-3.7.1.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js",
        "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js",
        "https://unpkg.com/jquery@3.7.1/dist/jquery.min.js",
    ],
    "js/vendor/bootstrap.bundle.min.js": [
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/5.3.2/js/bootstrap.bundle.min.js",
        "https://unpkg.com/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js",
    ],
    "js/vendor/select2.min.js": "https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js",
    "js/vendor/chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js",
    # Some templates include `chart.min.js`; ensure a proper minified Chart.js is available
    "js/vendor/chart.min.js": [
        "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.3.0/chart.min.js",
    ],
    "js/vendor/plotly.min.js": "https://cdn.plot.ly/plotly-2.24.1.min.js",
    "js/vendor/socket.io.min.js": "https://cdn.socket.io/4.7.2/socket.io.min.js",
    # Try multiple sources for libraries that move around or change package layout.
    "js/vendor/ace.js": [
        "https://cdnjs.cloudflare.com/ajax/libs/ace/1.15.6/ace.js",
        "https://cdnjs.cloudflare.com/ajax/libs/ace/1.4.14/ace.js",
        "https://cdn.jsdelivr.net/npm/ace-builds@1.4.14/src-min-noconflict/ace.js",
    ],
    "js/vendor/html5-qrcode.min.js": [
        "https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.7/minified/html5-qrcode.min.js",
        "https://unpkg.com/html5-qrcode@2.3.7/minified/html5-qrcode.min.js",
        "https://cdn.jsdelivr.net/gh/mebjas/html5-qrcode@2.3.7/minified/html5-qrcode.min.js",
    ],
    "js/vendor/jsQR.js": "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js",
    "js/vendor/jspdf.umd.min.js": "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
    "js/vendor/html2canvas.min.js": "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js",
    "js/vendor/chartjs-adapter-date-fns.bundle.min.js": "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2/dist/chartjs-adapter-date-fns.bundle.min.js",

    # CSS libraries (we'll parse CSS for referenced fonts and download them too)
    "css/vendor/bootstrap.min.css": "https://cdn.jsdelivr.net/npm/bootstrap@5/dist/css/bootstrap.min.css",
    "css/vendor/select2.min.css": "https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/css/select2.min.css",
    "css/vendor/fontawesome-all.min.css": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
    # Some templates reference older/simpler filename `fontawesome.min.css` or custom themes; ensure a copy exists
    "css/vendor/fontawesome.min.css": [
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/fontawesome.min.css",
    ],
    # Optional Select2 Bootstrap 5 theme (small separate file not included by default)
    "css/vendor/select2-bootstrap-5-theme.min.css": [
        "https://cdn.jsdelivr.net/npm/select2-bootstrap-5-theme@1.2.0/dist/select2-bootstrap-5-theme.min.css",
        "https://cdn.jsdelivr.net/gh/ttskch/select2-bootstrap-5-theme@1.2.0/dist/select2-bootstrap-5-theme.min.css",
    ],
}


def makedirs(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def download_url(url: str, dest: Path, force: bool = False, timeout: int = 20) -> bool:
    """Download a URL into dest. Return True on success, False on failure.
    If `force` is False and dest exists and size>0, skip download."""
    makedirs(dest.parent)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"Skipping existing: {dest} ({dest.stat().st_size} bytes)")
        return True

    print(f"Downloading {url} -> {dest}")
    try:
        req = Request(url, headers={"User-Agent": "fetch_vendors/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if not data:
                print(f"Warning: downloaded empty content for {url}")
            with open(dest, "wb") as f:
                f.write(data)
        return True
    except Exception as e:
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        print(f"Failed to download {url}: {e}")
        return False


CSS_URL_RE = re.compile(r"url\(([^)]+)\)")


def find_css_urls(css_text: str) -> list[str]:
    found = []
    for m in CSS_URL_RE.finditer(css_text):
        raw = m.group(1).strip().strip("'\"")
        if raw.startswith("data:"):
            continue
        found.append(raw)
    return found


def download_css_and_assets(css_url: str, dest: Path, force: bool = False) -> bool:
    """Download a CSS file, parse for url(...) references, download those assets,
    rewrite the CSS to reference a local `webfonts/` subdir and save it to dest."""
    makedirs(dest.parent)
    try:
        req = Request(css_url, headers={"User-Agent": "fetch_vendors/1.0"})
        with urlopen(req, timeout=20) as resp:
            css_bytes = resp.read()
            css_text = css_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Failed to fetch CSS {css_url}: {e}")
        return False

    urls = find_css_urls(css_text)
    if urls:
        webfonts_dir = dest.parent / "webfonts"
        makedirs(webfonts_dir)
        for raw in urls:
            # Resolve relative URLs against the CSS URL
            asset_url = urljoin(css_url, raw)
            parsed = urlparse(asset_url)
            name = Path(parsed.path).name
            local_asset = webfonts_dir / name
            ok = download_url(asset_url, local_asset, force=force)
            if not ok:
                print(f"Warning: failed to download asset referenced by CSS: {asset_url}")
            # replace occurrences of raw (may be quoted or unquoted) with webfonts/<name>
            css_text = css_text.replace(raw, f"webfonts/{name}")

    # Save rewritten CSS
    with open(dest, "wb") as f:
        f.write(css_text.encode("utf-8"))
    print(f"Saved CSS: {dest} ({dest.stat().st_size} bytes)")
    return True


def main(argv: list[str]) -> int:
    force = "--force" in argv

    success = True
    for rel, url_or_list in VENDORS.items():
        out = STATIC_DIR / rel
        out_parent = out.parent
        makedirs(out_parent)
        tried_any = False
        ok = False
        urls = url_or_list if isinstance(url_or_list, (list, tuple)) else [url_or_list]
        for url in urls:
            tried_any = True
            if rel.endswith(".css"):
                ok = download_css_and_assets(url, out, force=force)
            else:
                ok = download_url(url, out, force=force)
            if ok:
                break
            else:
                print(f"Attempt failed for {url}, trying next if available...")

        if not tried_any or not ok:
            success = False

    # Quick summary
    print("\nDownload summary:")
    for rel in sorted(VENDORS.keys()):
        path = STATIC_DIR / rel
        if path.exists():
            print(f"  OK: {rel} ({path.stat().st_size} bytes)")
        else:
            print(f"  MISSING: {rel}")

    if not success:
        print("Some files failed to download. Re-run with --force to retry or check network.")
        return 2
    print("All vendor files downloaded (or already present).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
