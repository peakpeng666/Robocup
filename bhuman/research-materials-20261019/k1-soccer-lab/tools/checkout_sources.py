#!/usr/bin/env python3
"""Fetch exact reviewed revisions into a new directory. Does not install packages."""

import argparse
import json
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path(__file__).resolve().parents[1] / "sources.lock.json")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--component", action="append", help="repeat to select components; default all locked repositories")
    args = parser.parse_args()
    if not args.destination.is_absolute():
        parser.error("--destination must be absolute")
    repositories = json.loads(args.lock.read_text())["repositories"]
    names = {repo["id"] for repo in repositories}
    if args.component and set(args.component) - names:
        parser.error("unknown component: " + str(set(args.component) - names))
    args.destination.mkdir(parents=True, exist_ok=True)
    for repo in repositories:
        if args.component and repo["id"] not in args.component:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_-]+", repo["id"]) or not re.fullmatch(r"[0-9a-f]{40}", repo["revision"]):
            raise ValueError("invalid locked name or commit")
        target = args.destination / repo["id"]
        if target.exists():
            raise FileExistsError(f"refusing to replace {target}; choose a fresh destination")
        run("git", "init", str(target))
        run("git", "-C", str(target), "remote", "add", "origin", repo["url"])
        run("git", "-C", str(target), "fetch", "--depth", "1", "origin", repo["revision"])
        run("git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD")
        actual = run("git", "-C", str(target), "rev-parse", "HEAD")
        if actual != repo["revision"]:
            raise RuntimeError("checkout revision mismatch")
        if (target / ".gitmodules").is_file():
            run("git", "-C", str(target), "submodule", "update", "--init", "--recursive")
        for submodule in repo.get("submodules", []):
            subpath = Path(submodule["path"])
            if subpath.is_absolute() or ".." in subpath.parts:
                raise ValueError("invalid submodule path")
            subactual = run("git", "-C", str(target / subpath), "rev-parse", "HEAD")
            if subactual != submodule["revision"]:
                raise RuntimeError(f"submodule revision mismatch: {subpath}")
        print(json.dumps({"component":repo["id"], "path":str(target), "revision":actual,
                          "submodules_initialized":(target / ".gitmodules").is_file()}))


if __name__ == "__main__":
    main()
