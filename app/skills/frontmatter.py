"""Strict, dependency-free parsing of the Agent Skills ``SKILL.md`` frontmatter.

Only the subset of YAML that the specification needs is accepted: top-level
``key: scalar`` pairs and one ``metadata`` mapping of string scalars. Anything
else is rejected instead of guessed, so the result never differs silently from
what a full YAML parser would produce for the same document.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .contracts import SkillPackageError

NAME_LIMIT = 64
DESCRIPTION_LIMIT = 1024
COMPATIBILITY_LIMIT = 500

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
# Plain scalars that YAML would turn into a non-string value.
_NON_STRING = re.compile(
    r"(?:~|null|Null|NULL|true|True|TRUE|false|False|FALSE|yes|Yes|YES|no|No|NO"
    r"|on|On|ON|off|Off|OFF|[-+]?(?:\d[\d_]*)?\.?\d[\d_]*(?:[eE][-+]?\d+)?"
    r"|[-+]?0[xXoObB][0-9A-Fa-f_]+|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))\Z"
)
_PLAIN_START_FORBIDDEN = frozenset("[]{}&*!|>'\"%@`#,?:-")


def _error(message: str) -> SkillPackageError:
    return SkillPackageError("invalid_skill_document", message)


@dataclass(frozen=True, slots=True)
class SkillDocument:
    """Validated standard metadata plus the Markdown instructions body."""

    name: str
    description: str
    body: str
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not (
            len(self.name) <= NAME_LIMIT and _NAME.fullmatch(self.name)
        ):
            raise _error("name must be 1-64 lowercase letters, digits and hyphens")
        if not isinstance(self.description, str) or not (
            self.description.strip() and len(self.description) <= DESCRIPTION_LIMIT
        ):
            raise _error("description must be 1-1024 characters")
        if self.compatibility is not None and not (
            self.compatibility.strip()
            and len(self.compatibility) <= COMPATIBILITY_LIMIT
        ):
            raise _error("compatibility must be 1-500 characters")
        for value in (self.license, self.allowed_tools):
            if value is not None and not value.strip():
                raise _error("optional fields must not be empty")
        if not isinstance(self.body, str):
            raise _error("instructions body must be text")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def _plain(value: str) -> str:
    comment = re.search(r"\s#", value)
    if comment:
        value = value[: comment.start()]
    value = value.strip()
    if not value:
        raise _error("empty values are not supported")
    if value[0] in _PLAIN_START_FORBIDDEN and not (
        value[0] == "-" and len(value) > 1 and value[1] != " "
    ):
        raise _error("value must be quoted")
    if ": " in value or value.endswith(":"):
        raise _error("values containing ': ' must be quoted")
    if _NON_STRING.fullmatch(value):
        raise _error("non-string values must be quoted")
    return value


def _double(value: str) -> str:
    result: list[str] = []
    index = 1
    escapes = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "/": "/"}
    while index < len(value):
        char = value[index]
        if char == '"':
            rest = value[index + 1 :].strip()
            if rest and not rest.startswith("#"):
                raise _error("unexpected content after quoted value")
            return "".join(result)
        if char == "\\":
            index += 1
            if index >= len(value) or value[index] not in escapes:
                raise _error("unsupported escape in quoted value")
            result.append(escapes[value[index]])
        else:
            result.append(char)
        index += 1
    raise _error("unterminated quoted value")


def _single(value: str) -> str:
    result: list[str] = []
    index = 1
    while index < len(value):
        char = value[index]
        if char == "'":
            if value[index + 1 : index + 2] == "'":
                result.append("'")
                index += 2
                continue
            rest = value[index + 1 :].strip()
            if rest and not rest.startswith("#"):
                raise _error("unexpected content after quoted value")
            return "".join(result)
        result.append(char)
        index += 1
    raise _error("unterminated quoted value")


def _scalar(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith('"'):
        return _double(stripped)
    if stripped.startswith("'"):
        return _single(stripped)
    return _plain(stripped)


def _split(line: str) -> tuple[str, str]:
    key, separator, value = line.partition(":")
    if not separator or not _KEY.fullmatch(key):
        raise _error("frontmatter lines must be 'key: value'")
    if value and not value.startswith(" "):
        raise _error("frontmatter lines must be 'key: value'")
    return key, value


def parse_skill_document(text: object) -> SkillDocument:
    if not isinstance(text, str):
        raise _error("SKILL.md must be UTF-8 text")
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        raise _error("SKILL.md must start with YAML frontmatter")
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r") == "---"
        )
    except StopIteration:
        raise _error("frontmatter is not closed") from None
    values: dict[str, object] = {}
    metadata: dict[str, str] | None = None
    metadata_indent: str | None = None
    for raw in lines[1:end]:
        line = raw.rstrip("\r")
        if "\t" in line:
            raise _error("tabs are not allowed in frontmatter")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] == " ":
            if metadata is None:
                raise _error("unexpected indentation")
            indent = line[: len(line) - len(line.lstrip(" "))]
            if metadata_indent is None:
                metadata_indent = indent
            elif indent != metadata_indent:
                raise _error("metadata entries must share one indentation")
            key, value = _split(line[len(indent) :])
            if not value.strip():
                raise _error("metadata values must be strings")
            if key in metadata:
                raise _error("duplicate metadata key")
            metadata[key] = _scalar(value)
            continue
        metadata = None
        key, value = _split(line)
        if key not in _FIELDS:
            raise _error(f"unsupported frontmatter field: {key}")
        if key in values:
            raise _error("duplicate frontmatter field")
        if key == "metadata":
            if value.strip():
                raise _error("metadata must be a block mapping")
            metadata = {}
            metadata_indent = None
            values[key] = metadata
            continue
        values[key] = _scalar(value)
    if "name" not in values or "description" not in values:
        raise _error("name and description are required")
    body = "\n".join(lines[end + 1 :]).strip()
    return SkillDocument(
        name=values["name"],  # type: ignore[arg-type]
        description=values["description"],  # type: ignore[arg-type]
        body=body,
        license=values.get("license"),  # type: ignore[arg-type]
        compatibility=values.get("compatibility"),  # type: ignore[arg-type]
        allowed_tools=values.get("allowed-tools"),  # type: ignore[arg-type]
        metadata=values.get("metadata") or {},  # type: ignore[arg-type]
    )
