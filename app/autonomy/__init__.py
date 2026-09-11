"""Runtime-owned autonomous computer-agent components.

from app.autonomy.orchestrator import AutonomousRuntime
from app.autonomy.task_engine import AutonomousTaskEngine

from app.autonomy.world_state import FactKind, WorldFact, WorldSnapshot, WorldStateManager
from app.autonomy.contracts import ActionContract, Idempotency, RetryPolicy
from app.autonomy.task_graph import GraphTask, GraphTaskStatus, TaskGraph, TaskScheduler
from app.autonomy.task_engine import GoalCompletionVerifier
from app.autonomy.planning import ContentTrust, PlanValidator, TaskContext, TaskContextManager
from app.autonomy.config import AutonomyLimits
from app.autonomy.observation import ScreenElement, ScreenObservation, ScreenUnderstandingProvider

from app.autonomy.team import AgentTeamBuilder, TeamAssignment
from app.autonomy.proposals import ActionRequest, ProposalRejected, ProposalType, ProposalValidator, ReasoningContext, ReasoningProposal, ReasoningProvider
from app.autonomy.world_model import CausalEvidence, CausalModel, Prediction, TransitionComparison, WorldModel
from app.autonomy.cognitive import CognitiveEngine, CounterfactualPlanner, Decision, DecisionEngine, Goal, IntentEngine, ObservationOption, PerceptionPlanner, Strategy
from app.autonomy.reasoning_provider import ChatbotReasoningProvider, ProviderResponseError, ReasoningDecisionProvider
from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.operator import AutonomousOperator, AutonomyMode, BlockerDetector, UserTakeoverManager
from app.autonomy.perception_service import PerceptionService
from app.autonomy.health import AgentHealth, AgentHealthMonitor
from app.autonomy.mode_policy import ModePolicy
from app.autonomy.task_runner import TaskEngineMissionRunner
from app.autonomy.triggers import FilesystemWatcher, ProcessWatcher, Trigger, TriggerEngine, TriggerKind, TriggerStore
from app.autonomy.benchmark import BenchmarkHarness, BenchmarkResult
from app.autonomy.monitoring import AutonomyMetrics, Interruption, InterruptionKind, InterruptionManager, UserPresenceDetector
from app.autonomy.event_store import EventStore

from app.autonomy.production_mission import RuntimeMissionComposer, VerifiedMissionCriterion
from app.autonomy.approvals import ApprovalRequest, ApprovalStatus, ApprovalStore, ApprovalSystem
from app.autonomy.governor import AutonomyGovernor, GovernorDecision, GovernorOutcome, MissionContract
from app.autonomy.capability_broker import CapabilityAssessment, CapabilityBroker, CapabilityStatus

__all__ = [
    "ActionContract", "ActionRequest", "AgentHealth", "AgentHealthMonitor", "AgentTeamBuilder",
    "ApprovalRequest", "ApprovalStatus", "ApprovalStore", "ApprovalSystem", "AutonomyGovernor",
    "AutonomyLimits", "AutonomyMetrics", "AutonomyMode", "AutonomousEvent", "AutonomousEventBus",
    "AutonomousOperator", "AutonomousRuntime", "AutonomousTaskEngine", "BenchmarkHarness",
    "BenchmarkResult", "BlockerDetector", "CapabilityAssessment", "CapabilityBroker",
    "CapabilityStatus", "CausalEvidence", "CausalModel", "ChatbotReasoningProvider",
    "CognitiveEngine", "ContentTrust", "CounterfactualPlanner", "Decision", "DecisionEngine",
    "EventStore", "EventType", "FactKind", "FilesystemWatcher", "Goal", "GoalCompletionVerifier",
    "GovernorDecision", "GovernorOutcome", "GraphTask", "GraphTaskStatus", "Idempotency",
    "IntentEngine", "Interruption", "InterruptionKind", "InterruptionManager", "Mission",
    "MissionContract", "MissionStatus", "MissionStore", "ModePolicy", "ObservationOption",
    "PerceptionPlanner", "PerceptionService", "PlanValidator", "Prediction", "ProcessWatcher",
    "ProposalRejected", "ProposalType", "ProposalValidator", "ProviderResponseError",
    "ReasoningContext", "ReasoningDecisionProvider", "ReasoningProposal", "ReasoningProvider",
    "RetryPolicy", "RuntimeMissionComposer", "ScreenElement", "ScreenObservation",
    "ScreenUnderstandingProvider", "Strategy", "TaskContext", "TaskContextManager",
    "TaskEngineMissionRunner", "TaskGraph", "TaskScheduler", "TeamAssignment", "TransitionComparison",
    "Trigger", "TriggerEngine", "TriggerKind", "TriggerStore", "UserPresenceDetector",
    "UserTakeoverManager", "VerifiedMissionCriterion", "WorldFact", "WorldModel", "WorldSnapshot",
    "WorldStateManager",
]
