"""Predictive state transitions, evidence-weighted causal knowledge, and simulation."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from app.autonomy.world_state import WorldSnapshot, WorldStateManager


@dataclass(frozen=True, slots=True)
class Prediction:
    action_id: str
    before_version: int
    expected: dict[str, Any]
    confidence: float


@dataclass(frozen=True, slots=True)
class TransitionComparison:
    prediction: Prediction
    observed_version: int
    differences: dict[str, tuple[Any, Any]]
    invalidated: bool


@dataclass(slots=True)
class CausalEvidence:
    action_type: str
    expected_effect: str
    observed_effect: str
    observations: int = 0
    supporting: int = 0

    @property
    def confidence(self) -> float:
        return self.supporting / self.observations if self.observations else 0.0


class CausalModel:
    """Evidence accumulates; a single observation never establishes causality."""
    def __init__(self) -> None: self._evidence: dict[tuple[str, str, str], CausalEvidence] = {}

    def observe(self, action_type: str, expected_effect: str, observed_effect: str) -> CausalEvidence:
        key = (action_type, expected_effect, observed_effect)
        evidence = self._evidence.setdefault(key, CausalEvidence(*key))
        evidence.observations += 1
        evidence.supporting += observed_effect == expected_effect
        return evidence

    def evidence(self) -> tuple[CausalEvidence, ...]: return tuple(self._evidence.values())


class WorldModel:
    """Runtime-owned model that compares simulated predictions with real observations."""
    def __init__(self, state: WorldStateManager | None = None, causal: CausalModel | None = None) -> None:
        self.state, self.causal = state or WorldStateManager(), causal or CausalModel()
        self.predictions: dict[str, Prediction] = {}

    def predict(self, action_id: str, expected: dict[str, Any], confidence: float = 0.5) -> Prediction:
        prediction = Prediction(action_id, self.state.snapshot().version, dict(expected), max(0.0, min(1.0, confidence)))
        self.predictions[action_id] = prediction
        return prediction

    def compare(self, action_id: str, observed: WorldSnapshot) -> TransitionComparison:
        prediction = self.predictions.pop(action_id)
        differences = {key: (value, observed.values().get(key)) for key, value in prediction.expected.items()
                       if observed.values().get(key) != value}
        for expected, actual in differences.values():
            self.causal.observe(action_id, str(expected), str(actual))
        if not differences:
            for value in prediction.expected.values(): self.causal.observe(action_id, str(value), str(value))
        return TransitionComparison(prediction, observed.version, differences, bool(differences))

    def export_state(self) -> dict[str, Any]:
        """Serializable runtime evidence for journals and crash checkpoints."""
        return {"predictions": [{"action_id": prediction.action_id, "before_version": prediction.before_version,
                "expected": prediction.expected, "confidence": prediction.confidence}
                for prediction in self.predictions.values()], "causal_evidence": [
                {"action_type": item.action_type, "expected_effect": item.expected_effect,
                 "observed_effect": item.observed_effect, "observations": item.observations,
                 "supporting": item.supporting, "confidence": item.confidence}
                for item in self.causal.evidence()]}

    def simulate(self, expected: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of a predicted state only; does not call tools or mutate reality."""
        simulated = self.state.snapshot().values()
        simulated.update(expected)
        return simulated
