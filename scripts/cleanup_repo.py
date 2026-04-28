"""scripts/cleanup_repo.py

Utility to analyze and optionally clean repository artifacts (dry-run by default).

Usage:
    python -m scripts.cleanup_repo [--delete] [--days N]

By default it only reports candidates: `temp/`, `output/`, `logs/`, `.cache/backups/`.
If `--delete` is provided it will remove files/directories (USE WITH CAUTION).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any


ROOT = Path(__file__).resolve().parent.parent


def _gather_dir(path: Path, older_than_days: int | None = None) -> Dict[str, Any]:
    info = {"path": str(path), "exists": path.exists(), "total_files": 0, "total_size": 0, "sample": []}
    if not path.exists():
        return info

    cutoff = None
    if older_than_days is not None:
        cutoff = datetime.now() - timedelta(days=older_than_days)

    files = []
    for p in path.rglob('*'):
        if p.is_file():
            try:
                stat = p.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)
                if cutoff and mtime > cutoff:
                    continue
                files.append((p, stat.st_size, mtime))
            except Exception:
                continue

    total = sum(s for _, s, _ in files)
    info["total_files"] = len(files)
    info["total_size"] = total
    info["sample"] = [str(f[0]) for f in files[:10]]
    return info


def analyze_repo(dry_run: bool = True, days: int = 30) -> Dict[str, Any]:
    candidates = [ROOT / '.cache' / 'backups', ROOT / 'temp', ROOT / 'output', ROOT / 'logs']
    report = {"dry_run": dry_run, "generated_at": datetime.now().isoformat(), "candidates": {}}

    for c in candidates:
        report["candidates"][str(c)] = _gather_dir(c, older_than_days=days)

    # also report large files in repo root temp
    large_files = []
    for p in (ROOT / 'temp').glob('*') if (ROOT / 'temp').exists() else []:
        try:
            if p.is_file() and p.stat().st_size > 1_000_000:
                large_files.append({"path": str(p), "size": p.stat().st_size})
        except Exception:
            continue

    report["large_files_in_temp"] = large_files
    return report


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    delete = False
    days = 30
    if '--delete' in argv:
        delete = True
    for i, a in enumerate(argv):
        if a in ('--days', '-d') and i + 1 < len(argv):
            try:
                days = int(argv[i + 1])
            except Exception:
                pass

    report = analyze_repo(dry_run=not delete, days=days)
    # Print concise summary
    print(f"Dry run: {not delete}")
    for path, info in report["candidates"].items():
        print(f"{path}: exists={info['exists']} files={info['total_files']} size={info['total_size']} bytes")
        if info['sample']:
            print("  sample:")
            for s in info['sample']:
                print(f"    - {s}")

    if report['large_files_in_temp']:
        print("Large files in temp:")
        for lf in report['large_files_in_temp']:
            print(f"  - {lf['path']} ({lf['size']} bytes)")

    if delete:
        # destructive path: remove files older than days
        for path_str, info in report["candidates"].items():
            p = Path(path_str)
            if not p.exists():
                continue
            for f in p.rglob('*'):
                try:
                    if f.is_file():
                        mtime = datetime.fromtimestamp(f.stat().st_mtime)
                        if mtime < datetime.now() - timedelta(days=days):
                            f.unlink()
                    else:
                        # attempt to remove empty dirs later
                        pass
                except Exception:
                    continue
        # try to remove empty dirs
        for path_str in list(report["candidates"].keys()):
            p = Path(path_str)
            if p.exists():
                for child in sorted(p.rglob('*'), reverse=True):
                    try:
                        if child.is_dir() and not any(child.iterdir()):
                            child.rmdir()
                    except Exception:
                        continue
        print("Deletion pass complete (files older than days removed).")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
