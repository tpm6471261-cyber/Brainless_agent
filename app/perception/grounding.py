"""Semantic and spatial target grounding over a fresh environment snapshot."""
from __future__ import annotations

from dataclasses import dataclass
import re

from app.autonomy.target import ResolvedTarget
from app.perception.models import EnvironmentSnapshot, UIElement


@dataclass(frozen=True, slots=True)
class TargetQuery:
    text: str
    role: str | None = None
    relation: str | None = None
    anchor: str | None = None
    ordinal: int | None = None


class ScreenGroundingEngine:
    """Ranks semantic evidence before geometry; ambiguity fails closed."""
    SOURCE_PRIORITY = {"accessibility": 6, "dom": 5, "application": 4,
                       "ocr": 3, "visual": 2, "controller": 1}

    def resolve(self, query: TargetQuery | str, snapshot: EnvironmentSnapshot,
                *, minimum_confidence: float = .65) -> ResolvedTarget | None:
        query = self.parse(query) if isinstance(query, str) else query
        candidates = [item for item in snapshot.visible_elements if item.visible and item.enabled]
        if query.role:
            candidates = [item for item in candidates if item.role.casefold() == query.role.casefold()]
        anchor = self._find_anchor(query.anchor, snapshot.visible_elements) if query.anchor else None
        scored = [(self._score(query, item, anchor), item) for item in candidates]
        scored = [(score, item) for score, item in scored if score >= minimum_confidence]
        scored.sort(key=lambda pair: (pair[0], self.SOURCE_PRIORITY.get(pair[1].source, 0)), reverse=True)
        if not scored:
            return None
        if query.ordinal:
            geometrically = sorted((item for _, item in scored), key=self._reading_order)
            if query.ordinal != -1 and query.ordinal > len(geometrically):
                return None
            selected = geometrically[-1 if query.ordinal == -1 else query.ordinal - 1]
            score = next(score for score, item in scored if item is selected)
        else:
            score, selected = scored[0]
            if len(scored) > 1 and abs(score - scored[1][0]) < .05:
                return None
        coordinates = None
        if selected.bounds:
            x, y, width, height = selected.bounds
            coordinates = (x + width // 2, y + height // 2)
        return ResolvedTarget(query.text, selected.source, score,
                              f"{selected.role}:{selected.label or selected.text}",
                              coordinates, selected.bounds, selected.element_id)

    def parse(self, text: str) -> TargetQuery:
        lowered = text.casefold()
        role = next((role for role in ("button", "textbox", "tab", "link", "checkbox",
                                       "dialog", "menuitem") if role in lowered), None)
        relation = next((word for word in ("below", "above", "left", "right", "near",
                                            "inside", "next to") if word in lowered), None)
        ordinal_words = {"first": 1, "second": 2, "third": 3, "last": -1}
        ordinal = next((value for word, value in ordinal_words.items() if word in lowered), None)
        anchor = None
        if relation:
            match = re.search(rf"{re.escape(relation)}(?: of)? (?:the )?(.+)$", lowered)
            anchor = match.group(1).strip(" .") if match else None
        return TargetQuery(text, role, relation, anchor, ordinal)

    def _score(self, query: TargetQuery, item: UIElement, anchor: UIElement | None) -> float:
        needle = self._terms(query.text)
        haystack = self._terms(f"{item.role} {item.label} {item.text}")
        semantic = len(needle & haystack) / max(1, len(needle))
        score = .55 * semantic + .35 * item.confidence + .1 * (
            self.SOURCE_PRIORITY.get(item.source, 0) / 6)
        if query.relation and anchor:
            score += .2 if self._related(item, anchor, query.relation) else -.4
        return min(1.0, max(0.0, score))

    @staticmethod
    def _terms(value: str) -> set[str]:
        ignored = {"click", "open", "select", "the", "a", "on", "to", "of", "below",
                   "above", "left", "right", "near", "next", "first", "second", "last"}
        return {part for part in re.findall(r"[\w-]+", value.casefold()) if part not in ignored}

    @classmethod
    def _find_anchor(cls, label: str, elements: tuple[UIElement, ...]) -> UIElement | None:
        terms = cls._terms(label)
        return max(elements, key=lambda item: len(terms & cls._terms(f"{item.label} {item.text}")),
                   default=None)

    @staticmethod
    def _reading_order(item: UIElement) -> tuple[int, int]:
        return (item.bounds[1], item.bounds[0]) if item.bounds else (10**9, 10**9)

    @staticmethod
    def _related(item: UIElement, anchor: UIElement, relation: str) -> bool:
        if not item.bounds or not anchor.bounds:
            return False
        x, y, width, height = item.bounds
        ax, ay, aw, ah = anchor.bounds
        centers = (x + width / 2, y + height / 2, ax + aw / 2, ay + ah / 2)
        ix, iy, anchor_x, anchor_y = centers
        return {"below": iy > anchor_y, "above": iy < anchor_y, "left": ix < anchor_x,
                "right": ix > anchor_x, "inside": x >= ax and y >= ay and x + width <= ax + aw
                and y + height <= ay + ah, "near": abs(ix-anchor_x)+abs(iy-anchor_y) < 300,
                "next to": abs(ix-anchor_x)+abs(iy-anchor_y) < 200}.get(relation, False)
