"""Command-line legacy trade importer; dry-run unless --apply is supplied."""

from __future__ import annotations

import argparse
import json

from legacy_trade_import import asdict, import_legacy_history
from trade_state_service import repository_for_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sqlite-path", default="optionbeacon_state.db")
    args = parser.parse_args()
    repository = repository_for_runtime(db_file=args.sqlite_path)
    reports = [
        asdict(
            import_legacy_history(
                path,
                repository,
                dry_run=not args.apply,
            )
        )
        for path in args.paths
    ]
    print(json.dumps(reports, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
