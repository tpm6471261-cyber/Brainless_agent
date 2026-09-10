"""Runtime-owned multimodal perception and semantic screen grounding."""
from app.perception.engine import MultimodalPerceptionEngine, PerceptionRequest
from app.perception.fusion import PerceptionFusionEngine
from app.perception.grounding import ScreenGroundingEngine, TargetQuery
from app.perception.models import (
    EnvironmentChange, EnvironmentSnapshot, PerceptionObservation, UIElement,
)
from app.perception.sources import BrowserDOMSource, ComputerControllerSource, FilesystemPerceptionSource, PerceptionSource
from app.perception.context import CommandSource, ContextBuilder, MultimodalCommand
from app.perception.providers import SpeechOutputProvider, SpeechRecognitionProvider, VisualUnderstandingProvider

__all__ = ["BrowserDOMSource", "CommandSource", "ComputerControllerSource", "ContextBuilder", "EnvironmentChange", "EnvironmentSnapshot",
           "MultimodalPerceptionEngine", "PerceptionFusionEngine", "PerceptionObservation",
           "PerceptionRequest", "PerceptionSource", "ScreenGroundingEngine", "TargetQuery",
           "FilesystemPerceptionSource", "MultimodalCommand", "SpeechOutputProvider", "SpeechRecognitionProvider", "UIElement",
           "VisualUnderstandingProvider"]
