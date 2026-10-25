"""Workbench configuration: root resolution and config loading."""
import json
import os
from pathlib import Path

WB_DIR = Path(__file__).resolve().parents[1]


def root() -> Path:
    override = os.environ.get("ROBOCUP_ROOT")
    if override:
        return Path(override).resolve()
    return WB_DIR.parent


def load(name: str) -> dict:
    with open(WB_DIR / "configs" / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


def project() -> dict:
    cfg = load("project.json")
    cfg["root"] = str(root())
    return cfg


def rp(rel: str) -> Path:
    """Resolve a root-relative path to an absolute path."""
    return (root() / rel).resolve()
