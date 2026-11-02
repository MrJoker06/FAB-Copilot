"""Strict, intentionally small release-version and comparator parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import SkillPackageError

_VERSION = re.compile(
    r"(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\Z"
)
_CLAUSE = re.compile(
    r"(==|>=|<=|>|<)?((?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5}))\Z"
)


@dataclass(frozen=True, order=True, slots=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(value: object) -> Version:
    if not isinstance(value, str) or len(value) > 24 or not _VERSION.fullmatch(value):
        raise SkillPackageError(
            "invalid_version", "version must be a strict x.y.z release"
        )
    return Version(*(int(part) for part in value.split(".")))


@dataclass(frozen=True, slots=True)
class VersionRequirement:
    clauses: tuple[tuple[str, Version], ...]

    def matches(self, value: object) -> bool:
        candidate = parse_version(value)
        return all(
            (operator == "==" and candidate == version)
            or (operator == ">=" and candidate >= version)
            or (operator == ">" and candidate > version)
            or (operator == "<=" and candidate <= version)
            or (operator == "<" and candidate < version)
            for operator, version in self.clauses
        )


def parse_version_requirement(value: object) -> VersionRequirement:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise SkillPackageError(
            "invalid_version_requirement", "version requirement is invalid"
        )
    if any(token in value for token in ("|", "^", "~", "*", " ")):
        raise SkillPackageError(
            "invalid_version_requirement", "version requirement uses unsupported syntax"
        )
    parts = value.split(",")
    if len(parts) > 8 or any(not part for part in parts):
        raise SkillPackageError(
            "invalid_version_requirement", "version requirement has invalid clauses"
        )
    clauses: list[tuple[str, Version]] = []
    for part in parts:
        matched = _CLAUSE.fullmatch(part)
        if not matched:
            raise SkillPackageError(
                "invalid_version_requirement", "version requirement has invalid clauses"
            )
        clauses.append((matched.group(1) or "==", parse_version(matched.group(2))))
    exact = {version for operator, version in clauses if operator == "=="}
    if len(exact) > 1:
        raise SkillPackageError(
            "invalid_version_requirement",
            "version requirement has contradictory exact versions",
        )
    lower = max(
        (version for operator, version in clauses if operator in {">", ">="}),
        default=None,
    )
    upper = min(
        (version for operator, version in clauses if operator in {"<", "<="}),
        default=None,
    )
    lower_strict = any(
        operator == ">" and version == lower for operator, version in clauses
    )
    upper_strict = any(
        operator == "<" and version == upper for operator, version in clauses
    )
    if (
        lower is not None
        and upper is not None
        and (lower > upper or (lower == upper and (lower_strict or upper_strict)))
    ):
        raise SkillPackageError(
            "invalid_version_requirement", "version requirement has impossible bounds"
        )
    requirement = VersionRequirement(tuple(clauses))
    if exact and not requirement.matches(str(next(iter(exact)))):
        raise SkillPackageError(
            "invalid_version_requirement",
            "version requirement excludes its exact version",
        )
    return requirement
