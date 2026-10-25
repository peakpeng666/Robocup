"""B-Human configuration semantics, reproduced in Python.

* ``search_path`` mirrors ``Settings::updateSearchPath`` (Src/Libs/Framework/Settings.cpp)
  and ``File::getFullNames`` (Src/Libs/Platform/File.cpp): the first existing file wins,
  ``Config/<name>`` is the final fallback.
* ``CfgDocument`` is a format-preserving reader for B-Human ``.cfg`` files
  (``key = value;``, nested ``{}``, arrays ``[]``, ``//`` and ``/* */`` comments).
  Only scalar values can be replaced, and every replacement is located by its full key
  path, so a patch can never silently land in the wrong block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import util

DEFAULT = "Default"


def search_path(config_dir: Path, robot_name: str, robot_type: str = "K1",
                location: str = DEFAULT, scenario: str = DEFAULT) -> list[Path]:
    config_dir = Path(config_dir)
    paths = [config_dir / "Robots" / robot_name]
    if location != DEFAULT:
        paths += [config_dir / "Locations" / location / robot_type, config_dir / "Locations" / location]
    if scenario != DEFAULT:
        paths += [config_dir / "Scenarios" / scenario / robot_type, config_dir / "Scenarios" / scenario]
    paths += [config_dir / "Robots/Default" / robot_type, config_dir / "Robots/Default",
              config_dir / "Locations/Default" / robot_type, config_dir / "Locations/Default",
              config_dir / "Scenarios/Default" / robot_type, config_dir / "Scenarios/Default",
              config_dir]
    return paths


def resolve(config_dir: Path, name: str, **settings) -> Path | None:
    for directory in search_path(config_dir, **settings):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def candidate_names(config_dir: Path, **settings) -> set[str]:
    """Every file name that is directly inside one of the search-path directories."""
    names = set()
    for directory in search_path(config_dir, **settings):
        if directory.is_dir():
            names.update(p.name for p in directory.iterdir() if p.is_file())
    return names


def resolution_table(config_dir: Path, names=None, **settings) -> dict[str, dict]:
    """{name: {"path": relative path, "sha256": digest}} for what a robot actually loads."""
    config_dir = Path(config_dir)
    names = sorted(names if names is not None else candidate_names(config_dir, **settings))
    table = {}
    for name in names:
        path = resolve(config_dir, name, **settings)
        if path is not None:
            table[name] = {"path": path.relative_to(config_dir).as_posix(), "sha256": util.sha256_file(path)}
    return table


# --------------------------------------------------------------------------- cfg files

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<line_comment>//[^\n]*)
  | (?P<block_comment>/\*.*?\*/)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<punct>[={}\[\];,])
  | (?P<atom>[^\s={}\[\];,"]+)
""", re.VERBOSE | re.DOTALL)


@dataclass
class Scalar:
    path: str
    start: int
    end: int
    text: str


class CfgError(ValueError):
    pass


class CfgDocument:
    def __init__(self, text: str, origin: str = "<cfg>"):
        self.text = text
        self.origin = origin
        self.scalars: dict[str, Scalar] = {}
        self._parse()

    @classmethod
    def load(cls, path) -> "CfgDocument":
        return cls(Path(path).read_text(encoding="utf-8"), str(path))

    def _tokens(self):
        position = 0
        while position < len(self.text):
            match = _TOKEN.match(self.text, position)
            if not match:
                raise CfgError(f"{self.origin}: cannot tokenize at offset {position}")
            kind = match.lastgroup
            if kind not in ("ws", "line_comment", "block_comment"):
                yield kind, match.group(), match.start(), match.end()
            position = match.end()

    def _parse(self):
        tokens = list(self._tokens())
        index = 0

        def peek():
            return tokens[index] if index < len(tokens) else (None, None, None, None)

        def take(expected=None):
            nonlocal index
            token = peek()
            if token[0] is None:
                raise CfgError(f"{self.origin}: unexpected end of file")
            if expected is not None and token[1] != expected:
                raise CfgError(f"{self.origin}: expected {expected!r} at offset {token[2]}, got {token[1]!r}")
            index += 1
            return token

        def value(path):
            kind, text, start, end = peek()
            if text == "{":
                take("{")
                members(path, "}")
                take("}")
            elif text == "[":
                take("[")
                element = 0
                while peek()[1] != "]":
                    value(f"{path}[{element}]")
                    element += 1
                    if peek()[1] == ",":
                        take(",")
                take("]")
            elif kind in ("atom", "string"):
                # A scalar may be an expression such as ``xPosOwnGoalLine + 1000``.
                take()
                last_end = end
                while peek()[0] in ("atom", "string"):
                    last_end = take()[3]
                if path in self.scalars:
                    raise CfgError(f"{self.origin}: duplicate key {path}")
                self.scalars[path] = Scalar(path, start, last_end, self.text[start:last_end])
            else:
                raise CfgError(f"{self.origin}: unexpected {text!r} at offset {start}")

        def members(prefix, closing):
            while peek()[1] not in (closing, None):
                kind, name, start, _ = take()
                if kind != "atom":
                    raise CfgError(f"{self.origin}: expected a key at offset {start}, got {name!r}")
                take("=")
                value(f"{prefix}.{name}" if prefix else name)
                take(";")

        members("", None)
        if index != len(tokens):
            raise CfgError(f"{self.origin}: trailing tokens")

    def get(self, path: str) -> str:
        if path not in self.scalars:
            raise CfgError(f"{self.origin}: no scalar at {path}")
        text = self.scalars[path].text
        return text[1:-1] if text.startswith('"') else text

    def with_values(self, changes: dict[str, str]) -> str:
        """Like ``patched`` but also inserts missing scalars into their (existing) parent block."""
        existing = {k: v for k, v in changes.items() if k in self.scalars}
        text = self.patched(existing) if existing else self.text
        missing = {k: v for k, v in changes.items() if k not in self.scalars}
        for path, value in missing.items():
            document = CfgDocument(text, self.origin)
            parent, _, key = path.rpartition(".")
            siblings = [s for p, s in document.scalars.items() if p.rpartition(".")[0] == parent and "[" not in p]
            if not siblings:
                raise CfgError(f"{self.origin}: cannot insert {path}: parent block has no scalar members")
            anchor = max(siblings, key=lambda s: s.end)
            semicolon = text.index(";", anchor.end)
            line_start = text.rfind("\n", 0, anchor.start) + 1
            indent = re.match(r"[ \t]*", text[line_start:]).group(0)
            text = text[:semicolon + 1] + f"\n{indent}{key} = {value};" + text[semicolon + 1:]
        result = CfgDocument(text, self.origin + " (with values)")
        for path, value in changes.items():
            if result.get(path) != str(value):
                raise CfgError(f"{self.origin}: {path} did not take value {value}")
        return text

    def patched(self, changes: dict[str, str]) -> str:
        """Return new text with scalars replaced; every key must exist exactly once."""
        edits = []
        for path, new_value in changes.items():
            if path not in self.scalars:
                raise CfgError(f"{self.origin}: patch target {path} does not exist")
            new_text = str(new_value)
            if not new_text or re.search(r'[\s={}\[\];,"]', new_text):
                new_text = '"' + new_text.replace("\\", "\\\\").replace('"', '\\"') + '"'
            scalar = self.scalars[path]
            edits.append((scalar.start, scalar.end, new_text))
        result = self.text
        for start, end, new_text in sorted(edits, reverse=True):
            result = result[:start] + new_text + result[end:]
        CfgDocument(result, self.origin + " (patched)")  # must still parse
        return result
