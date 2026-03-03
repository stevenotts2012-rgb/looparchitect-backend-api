"""Identify and optionally delete loop records whose source files are missing locally.

Usage:
  python scripts/cleanup_orphan_loops.py
  python scripts/cleanup_orphan_loops.py --delete
  python scripts/cleanup_orphan_loops.py --limit 50
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop


def resolve_local_path(file_key: str) -> Path:
    filename = Path(file_key).name
    return Path("uploads") / filename


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cleanup orphan loop records")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete orphaned loop records (default is dry-run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of orphaned records to process (0 = all)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()

    try:
        loops = db.query(Loop).filter(Loop.file_key.isnot(None)).order_by(Loop.id.asc()).all()
        referenced_loop_ids = {
            row[0] for row in db.query(Arrangement.loop_id).distinct().all() if row[0] is not None
        }

        orphans: list[Loop] = []
        protected_orphans: list[Loop] = []
        for loop in loops:
            if not loop.file_key:
                continue
            local_path = resolve_local_path(loop.file_key)
            if not local_path.exists():
                if loop.id in referenced_loop_ids:
                    protected_orphans.append(loop)
                else:
                    orphans.append(loop)

        if args.limit > 0:
            orphans = orphans[: args.limit]

        print(f"Total loops checked: {len(loops)}")
        print(f"Orphans found (unreferenced): {len(orphans)}")
        print(f"Orphans skipped (referenced by arrangements): {len(protected_orphans)}")

        if not orphans:
            print("No orphaned loops found.")
            return 0

        print("\nSample orphaned loops:")
        for loop in orphans[:20]:
            print(f"- id={loop.id} file_key={loop.file_key}")

        if protected_orphans:
            print("\nSample protected orphaned loops (still referenced):")
            for loop in protected_orphans[:10]:
                print(f"- id={loop.id} file_key={loop.file_key}")

        if not args.delete:
            print("\nDry run only. Re-run with --delete to remove these records.")
            return 0

        deleted = 0
        for loop in orphans:
            db.delete(loop)
            deleted += 1

        db.commit()
        print(f"\nDeleted orphaned loops: {deleted}")
        return 0

    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
