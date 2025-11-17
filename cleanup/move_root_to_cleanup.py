"""
Move selected top-level .md and .py files into cleanup/.

This script is intended to be run from the repository root.
It will move the listed files into the `cleanup/` directory, creating
the directory if necessary. Files explicitly kept are not moved.

Per user instruction, `update_from_github_file.py` and
`prepare_for_publish.py` are kept in the root.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
CLEANUP = ROOT / 'cleanup'
CLEANUP.mkdir(exist_ok=True)

# Files to keep in root (do not move)
KEEP = {'update_from_github_file.py', 'prepare_for_publish.py', 'run.py'}

# Move all top-level .md and .py files except those in KEEP
def gather_targets(root: Path):
    targets = []
    for p in root.iterdir():
        if p.is_file():
            if p.suffix in {'.md', '.py'} and p.name not in KEEP:
                # avoid moving files inside cleanup folder (already in cleanup)
                if p.parent == root:
                    targets.append(p)
    return targets

def move_files(files, dest: Path):
    moved = []
    skipped = []
    errors = []
    for f in files:
        try:
            target = dest / f.name
            # If the dest already has a file with same name, append a suffix
            if target.exists():
                # add numeric suffix until unique
                i = 1
                stem = f.stem
                while True:
                    candidate = dest / f"{stem}.dup{i}{f.suffix}"
                    if not candidate.exists():
                        target = candidate
                        break
                    i += 1
            shutil.move(str(f), str(target))
            moved.append((str(f), str(target)))
        except Exception as e:
            errors.append((str(f), str(e)))
    return moved, skipped, errors

def main():
    targets = gather_targets(ROOT)
    if not targets:
        print('No top-level .md or .py files found to move (or all are in KEEP).')
        return 0
    print(f'Found {len(targets)} files to move.')
    for t in targets:
        print(' -', t.name)
    moved, skipped, errors = move_files(targets, CLEANUP)
    print('\nSummary:')
    print(f'  Moved: {len(moved)}')
    for src, dst in moved:
        print(f'    {src} -> {dst}')
    if skipped:
        print(f'  Skipped: {len(skipped)}')
    if errors:
        print(f'  Errors: {len(errors)}')
        for f, err in errors:
            print(f'    {f}: {err}')
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
