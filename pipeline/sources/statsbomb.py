"""Download the configured slice of StatsBomb Open Data at a pinned commit.

WHY a partial clone + sparse checkout: the open-data repository is several GB (every
competition, plus 360 freeze frames). A shallow, blob-less fetch downloads only commit and
tree objects; the sparse checkout then pulls just the blobs for the files we ask for.

The match list is only known after reading the matches files, so the checkout happens in
two steps: competitions + matches first, then events + lineups for those matches.
"""

import json
import subprocess
from pathlib import Path
from typing import Any


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _sparse_set(repo: Path, patterns: list[str]) -> None:
    # --no-cone: we select individual files, not whole directories.
    _git(repo, "sparse-checkout", "set", "--no-cone", "--stdin", stdin="\n".join(patterns) + "\n")


def fetch(source: dict[str, Any], dest: Path) -> list[int]:
    """Check out source["commit"] into dest with only the configured files. Returns match IDs."""
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        _git(dest, "init", "--quiet")
        _git(dest, "remote", "add", "origin", source["repo"])
    else:
        _git(dest, "remote", "set-url", "origin", source["repo"])
    # Files are hashed byte-for-byte by the ingest: never let git rewrite line endings.
    _git(dest, "config", "core.autocrlf", "false")

    commit = source["commit"]
    _git(dest, "fetch", "--quiet", "--depth=1", "--filter=blob:none", "origin", commit)

    matches_files = [
        f"data/matches/{c['competition_id']}/{c['season_id']}.json" for c in source["competitions"]
    ]
    base = ["/data/competitions.json", *(f"/{p}" for p in matches_files)]
    _sparse_set(dest, base)
    _git(dest, "checkout", "--quiet", "--detach", commit)

    match_ids = sorted(
        match["match_id"]
        for path in matches_files
        for match in json.loads((dest / path).read_text(encoding="utf-8"))
    )
    per_match = [f"/data/{entity}/{mid}.json" for mid in match_ids for entity in ("events", "lineups")]
    _sparse_set(dest, base + per_match)
    return match_ids


def checked_out_commit(dest: Path) -> str:
    return _git(dest, "rev-parse", "HEAD").strip()
