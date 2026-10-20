#!/usr/bin/env python3
"""RoboCup post-match evidence extractor for LLM-written Chinese reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from extract_evidence import build_evidence, render_evidence_html, render_llm_brief
from telemetry_core import default_analyses_dir, default_recordings_dir


def output_paths(recording: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    return (
        out_dir / f"{recording.stem}_evidence.json",
        out_dir / f"{recording.stem}_brief.md",
        out_dir / f"{recording.stem}_evidence.html",
    )


def analyse_one(
    recording: Path,
    *,
    out_dir: Path,
    viewer_url: str,
    force: bool = False,
    brief_out: Path | None = None,
) -> tuple[Path, Path, Path]:
    recording = recording.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path, brief_path, html_path = output_paths(recording, out_dir)
    if brief_out is not None:
        brief_path = brief_out
        brief_path.parent.mkdir(parents=True, exist_ok=True)

    if not force and evidence_path.exists() and brief_path.exists() and html_path.exists():
        print(f"Skipping {recording.name} (evidence, brief, and HTML already exist)")
        return evidence_path, brief_path, html_path

    print(f"Extracting evidence from {recording.name} ...")
    evidence = build_evidence(recording, viewer_url=viewer_url)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    brief_path.write_text(render_llm_brief(evidence), encoding="utf-8")
    html_path.write_text(render_evidence_html(evidence), encoding="utf-8")
    print(f"  evidence -> {evidence_path}")
    print(f"  brief    -> {brief_path}")
    print(f"  html     -> {html_path}")
    return evidence_path, brief_path, html_path


def analyse_all(recordings_dir: Path, *, out_dir: Path, viewer_url: str, force: bool = False) -> list[tuple[Path, Path, Path]]:
    if not recordings_dir.is_dir():
        print(f"No recordings directory at {recordings_dir}", file=sys.stderr)
        sys.exit(1)
    outputs: list[tuple[Path, Path, Path]] = []
    for recording in sorted(recordings_dir.glob("*.jsonl")):
        evidence_path, brief_path, html_path = output_paths(recording, out_dir)
        if not force and evidence_path.exists() and brief_path.exists() and html_path.exists():
            print(f"Skipping {recording.name} (evidence, brief, and HTML already exist)")
            continue
        outputs.append(analyse_one(recording, out_dir=out_dir, viewer_url=viewer_url, force=force))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract deterministic RoboCup match evidence for LLM-written Chinese reports"
    )
    parser.add_argument("recording", nargs="?", type=Path, help="Path to a .jsonl recording")
    parser.add_argument("--all", action="store_true", help="Analyse every .jsonl recording")
    parser.add_argument("--recordings-dir", type=Path, default=default_recordings_dir(), help="Directory used by --all")
    parser.add_argument("--out-dir", type=Path, default=default_analyses_dir(), help="Directory for evidence/brief files")
    parser.add_argument("--viewer-url", default="http://127.0.0.1:8090", help="Base URL for replay deep links")
    parser.add_argument("--force", action="store_true", help="Overwrite existing evidence/brief outputs")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Compatibility alias: write the generated LLM brief to this Markdown path for single-recording runs",
    )
    args = parser.parse_args()

    if args.all:
        analyse_all(args.recordings_dir.resolve(), out_dir=args.out_dir.resolve(), viewer_url=args.viewer_url, force=args.force)
        return

    if args.recording is None:
        parser.print_help()
        sys.exit(1)

    recording = args.recording
    if not recording.is_absolute():
        recording = Path.cwd() / recording
    if not recording.is_file():
        print(f"File not found: {recording}", file=sys.stderr)
        sys.exit(1)
    analyse_one(recording, out_dir=args.out_dir.resolve(), viewer_url=args.viewer_url, force=args.force, brief_out=args.out)


if __name__ == "__main__":
    main()
