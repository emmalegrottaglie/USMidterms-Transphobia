"""Collectors: each module turns an external source into hourly points."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Result:
    """Hourly points by series key (stamped at each hour end) and the errors met on the way."""

    points: dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
