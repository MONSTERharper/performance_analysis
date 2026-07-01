#!/usr/bin/env python3
"""Performance analysis CLI for MongoDB scanner data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analysis import (
    error_analysis,
    inventory,
    load_time,
    regression,
    scanner_stoppages,
    sites,
    slide_counts,
)
from analysis.export import export_all_collections, export_collection
from db.connection import get_client, list_all_collections


OUTPUT_DIR = Path("output")

ANALYSIS_MODULES = {
    "inventory": inventory,
    "stoppages": scanner_stoppages,
    "errors": error_analysis,
    "load_time": load_time,
    "regression": regression,
    "sites": sites,
    "slides": slide_counts,
}


def cmd_ping(_: argparse.Namespace) -> int:
    client = get_client()
    client.admin.command("ping")
    dbs = [db for db in client.list_database_names() if db not in {"admin", "config", "local"}]
    print(f"Connected to MongoDB. Analytics databases: {', '.join(dbs)}")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    df = inventory.build_inventory()
    inventory.print_inventory(df)
    if args.save:
        path = inventory.save_inventory(df, OUTPUT_DIR)
        print(f"\nSaved to {path}")
        if args.schemas:
            schema_paths = inventory.save_all_schemas(OUTPUT_DIR / "schemas")
            print(f"Saved {len(schema_paths)} schema files to {OUTPUT_DIR / 'schemas'}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    modules = list(ANALYSIS_MODULES.keys()) if args.all else (args.modules or [])
    output = OUTPUT_DIR if args.save else None

    for name in modules:
        if name == "inventory":
            df = inventory.build_inventory()
            inventory.print_inventory(df)
            if output:
                inventory.save_inventory(df, output)
            continue

        module = ANALYSIS_MODULES.get(name)
        if module and hasattr(module, "run_analysis"):
            module.run_analysis(output)

    if output:
        print(f"\nAll reports saved to {output.resolve()}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if args.collection:
        db_name, coll_name = args.collection.split(".", 1)
        path = export_collection(db_name, coll_name, output, fmt=args.format, limit=args.limit)
        if path:
            print(f"Exported to {path}")
        else:
            print("No documents found.")
            return 1
    else:
        print(f"Exporting all collections to {output}/ ...\n")
        paths = export_all_collections(output, fmt=args.format)
        print(f"\nExported {len(paths)} collections.")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    print("\nAvailable collections:\n")
    for db_name, coll_name in list_all_collections():
        count = get_client()[db_name][coll_name].estimated_document_count()
        print(f"  {db_name}.{coll_name:<45} ~{count:,} docs")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze scanner performance data from MongoDB",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ping = sub.add_parser("ping", help="Test MongoDB connection")
    ping.set_defaults(func=cmd_ping)

    inv = sub.add_parser("inventory", help="List all databases and collections")
    inv.add_argument("--save", action="store_true", help="Save inventory to output/")
    inv.add_argument("--schemas", action="store_true", help="Also export field schemas")
    inv.set_defaults(func=cmd_inventory)

    analyze = sub.add_parser("analyze", help="Run performance analyses")
    analyze.add_argument(
        "--module",
        dest="modules",
        action="append",
        choices=list(ANALYSIS_MODULES.keys()),
        help="Analysis module to run (repeatable; use --all for every module)",
    )
    analyze.add_argument("--all", action="store_true", help="Run all analysis modules")
    analyze.add_argument("--save", action="store_true", help="Save results to output/")
    analyze.set_defaults(func=cmd_analyze, modules=None)

    export = sub.add_parser("export", help="Export raw collection data")
    export.add_argument(
        "--collection",
        help="Collection to export as db.collection (e.g. test_db2.scanner_stoppages)",
    )
    export.add_argument("--output", default="output/raw", help="Output directory")
    export.add_argument("--format", choices=["csv", "json"], default="csv")
    export.add_argument("--limit", type=int, help="Max documents to export")
    export.set_defaults(func=cmd_export)

    lst = sub.add_parser("list", help="List all collections with document counts")
    lst.set_defaults(func=cmd_list)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyze" and not args.all and not args.modules:
        print("Specify --module or use --all. Example: python main.py analyze --all --save")
        parser.parse_args(["analyze", "--help"])
        return 1

    try:
        return args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
