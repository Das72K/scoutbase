"""`scoutbase` command line: fetch provider data."""

import argparse
import sys

from pipeline.config import SOURCES_DIR, load_sources
from pipeline.sources import statsbomb as source_statsbomb


def fetch_statsbomb() -> int:
    source = load_sources()["statsbomb"]
    match_ids = source_statsbomb.fetch(source, SOURCES_DIR / "statsbomb")
    print(f"statsbomb @ {source['commit'][:12]}: {len(source['competitions'])} seasons, "
          f"{len(match_ids)} matches -> {SOURCES_DIR / 'statsbomb'}")
    return 0


COMMANDS = {
    ("fetch", "statsbomb"): fetch_statsbomb,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="scoutbase")
    parser.add_argument("command", choices=sorted({c for c, _ in COMMANDS}))
    parser.add_argument("provider", choices=sorted({p for _, p in COMMANDS}))
    args = parser.parse_args()
    sys.exit(COMMANDS[(args.command, args.provider)]())


if __name__ == "__main__":
    main()
