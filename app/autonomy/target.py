"""Confidence-scored semantic target resolution with deterministic fallbacks."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.autonomy.models import ComputerState


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    target: str
    method: str
    confidence: float
    evidence: str
    coordinates: tuple[int, int] | None = None
    bounding_box: tuple[int, int, int, int] | None = None
    target_id: str = ""

    def __post_init__(self) -> None:
        if not self.target_id:
            object.__setattr__(self, "target_id", str(uuid4()))


class TargetProvider(Protocol):
    def resolve(self, query: str, state: ComputerState) -> ResolvedTarget | None: ...


class TargetResolver:
    def __init__(self, providers: tuple[TargetProvider, ...] = (), confidence_threshold: float = .75) -> None:
        self.providers, self.confidence_threshold = providers, confidence_threshold

    def resolve(self, query: str, state: ComputerState, *, coordinate_fallback: tuple[int, int] | None = None) -> ResolvedTarget | None:
        candidates = [candidate for provider in self.providers if (candidate := provider.resolve(query, state))]
        # Text matching is a safe generic provider from the current observed UI.
        lowered = query.casefold()
        for text in state.visible_ui:
            if lowered in text.casefold():
                candidates.append(ResolvedTarget(query, "text", .8, text))
        if coordinate_fallback:
            candidates.append(ResolvedTarget(query, "coordinates", .2, "explicit fallback", coordinate_fallback))
        eligible = [item for item in candidates if item.confidence >= self.confidence_threshold]
        # Prefer deterministic semantic sources over visual/coordinate fallbacks
        # whenever their confidence is comparable.
        priority = {"accessibility": 5, "dom": 4, "text": 3, "visual": 2, "coordinates": 1}
        return max(eligible, key=lambda item: (item.confidence, priority.get(item.method, 0)), default=None)

    def resolve_environment(self, query: str, snapshot, *, minimum_confidence: float | None = None) -> ResolvedTarget | None:
        """Resolve normalized UI semantically; kept separate from legacy ComputerState callers."""
        from app.perception.grounding import ScreenGroundingEngine
        return ScreenGroundingEngine().resolve(query, snapshot,
            minimum_confidence=self.confidence_threshold if minimum_confidence is None else minimum_confidence)
