"""Data models for merit badges and their requirement trees."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterator


@dataclass
class Requirement:
    """A single requirement node. Children are sub-requirements (a, b, (1)...)."""

    marker: str  # "1", "a", "(1)", "ii" - as printed on the page
    text: str
    level: int = 1
    notes: list[str] = field(default_factory=list)
    children: list["Requirement"] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Marker rendered for display, e.g. '1.', 'a.', '(1)'."""
        m = self.marker
        if m.startswith("("):
            return m
        return f"{m}."

    def walk(self, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], "Requirement"]]:
        """Yield (path, node) for this node and every descendant, depth first.

        ``path`` is the chain of markers, so requirement 3.b.(2) yields
        ``("3", "b", "(2)")``.
        """
        here = path + (self.marker,)
        yield here, self
        for child in self.children:
            yield from child.walk(here)

    def count(self) -> int:
        return 1 + sum(c.count() for c in self.children)


@dataclass
class Badge:
    """A merit badge and its parsed requirements."""

    name: str
    slug: str
    url: str
    eagle_required: bool = False
    overview: str = ""
    requirements: list[Requirement] = field(default_factory=list)
    source_retrieved: str = ""  # ISO timestamp
    version_note: str = ""  # e.g. "2025 Scouts BSA Requirements (33216)"

    def total_requirements(self) -> int:
        return sum(r.count() for r in self.requirements)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Badge":
        def build(node: dict[str, Any]) -> Requirement:
            return Requirement(
                marker=node["marker"],
                text=node["text"],
                level=node.get("level", 1),
                notes=list(node.get("notes", [])),
                children=[build(c) for c in node.get("children", [])],
            )

        return cls(
            name=data["name"],
            slug=data["slug"],
            url=data["url"],
            eagle_required=data.get("eagle_required", False),
            overview=data.get("overview", ""),
            requirements=[build(r) for r in data.get("requirements", [])],
            source_retrieved=data.get("source_retrieved", ""),
            version_note=data.get("version_note", ""),
        )


@dataclass
class CatalogEntry:
    """One row of the A-Z merit badge index."""

    name: str
    slug: str
    url: str
    eagle_required: bool = False
