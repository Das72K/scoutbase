"""`scoutbase` command line: fetch provider data and ingest it into raw."""

import argparse
import sys
import time

from pipeline.config import connect_pipeline, load_sources, sources_dir
from pipeline.ingest import statsbomb as ingest_statsbomb
from pipeline.sources import statsbomb as source_statsbomb


def fetch_statsbomb(args: argparse.Namespace) -> int:
    source = load_sources()["statsbomb"]
    dest = sources_dir() / "statsbomb"
    match_ids = source_statsbomb.fetch(source, dest)
    print(f"statsbomb @ {source['commit'][:12]}: {len(source['competitions'])} seasons, "
          f"{len(match_ids)} matches -> {dest}")
    return 0


def ingest_statsbomb_cmd(args: argparse.Namespace) -> int:
    root = sources_dir() / "statsbomb"
    if not (root / ".git").exists():
        print(f"{root} not found: run `make fetch-statsbomb` first", file=sys.stderr)
        return 1
    started = time.perf_counter()
    with connect_pipeline() as conn:
        run = ingest_statsbomb.ingest(
            conn, root, source_statsbomb.checked_out_commit(root), verify=args.verify
        )
    elapsed = time.perf_counter() - started
    print(f"run {run.run_id} {run.status} in {elapsed:.1f}s ({root}): {run.files_seen} files seen, "
          f"{run.files_loaded} loaded, {run.files_replaced} replaced, {run.files_skipped} skipped, "
          f"{run.files_hashed} hashed, {run.rows_loaded} rows loaded")
    if run.error:
        print(f"error: {run.error}", file=sys.stderr)
    return 0 if run.status == "succeeded" else 1


COMMANDS = {
    ("fetch", "statsbomb"): fetch_statsbomb,
    ("ingest", "statsbomb"): ingest_statsbomb_cmd,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="scoutbase")
    parser.add_argument("command", choices=sorted({c for c, _ in COMMANDS}))
    parser.add_argument("provider", choices=sorted({p for _, p in COMMANDS}))
    parser.add_argument(
        "--verify", action="store_true",
        help="ingest only: hash every file, even when its size and mtime are unchanged",
    )
    args = parser.parse_args()
    if args.verify and args.command != "ingest":
        parser.error("--verify only applies to ingest")
    sys.exit(COMMANDS[(args.command, args.provider)](args))


if __name__ == "__main__":
    main()
