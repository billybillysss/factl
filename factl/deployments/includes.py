from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolvedIncludeMatch:
    normalized_include: str
    relative_path: str
    full_path: Path
    is_dir: bool
    is_pattern: bool


def normalize_include_path(path: str) -> str:
    return path.replace("\\", "/").strip("/").strip()


def resolve_include_matches(root: Path, include: str) -> list[ResolvedIncludeMatch]:
    normalized_include = normalize_include_path(include)
    if not normalized_include:
        return []

    literal_path = root / Path(normalized_include)
    if literal_path.exists():
        return [
            ResolvedIncludeMatch(
                normalized_include=normalized_include,
                relative_path=literal_path.relative_to(root).as_posix(),
                full_path=literal_path,
                is_dir=literal_path.is_dir(),
                is_pattern=False,
            )
        ]

    matches = sorted(root.glob(normalized_include), key=lambda path: str(path).lower())
    return [
        ResolvedIncludeMatch(
            normalized_include=normalized_include,
            relative_path=path.relative_to(root).as_posix(),
            full_path=path,
            is_dir=path.is_dir(),
            is_pattern=True,
        )
        for path in matches
    ]
