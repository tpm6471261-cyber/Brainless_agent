"""Runtime-owned autonomous computer-agent components."""

from app.autonomy.orchestrator import AutonomousRuntime
from app.autonomy.task_engine import AutonomousTaskEngine

__all__ = ["AutonomousRuntime", "AutonomousTaskEngine"]

from app.autonomy.world_state import FactKind, WorldFact, WorldSnapshot, WorldStateManager
from app.autonomy.contracts import ActionContract, Idempotency, RetryPolicy
from app.autonomy.task_graph import GraphTask, GraphTaskStatus, TaskGraph, TaskScheduler
from app.autonomy.task_engine import GoalCompletionVerifier
from app.autonomy.planning import ContentTrust, PlanValidator, TaskContext, TaskContextManager
from app.autonomy.config import AutonomyLimits
from app.autonomy.observation import ScreenElement, ScreenObservation, ScreenUnderstandingProvider

__all__ = ["AutonomousRuntime", "AutonomousTaskEngine", "FactKind", "WorldFact", "WorldSnapshot", "WorldStateManager", "ActionContract", "Idempotency", "RetryPolicy", "GraphTask", "GraphTaskStatus", "TaskGraph", "TaskScheduler", "GoalCompletionVerifier", "ContentTrust", "PlanValidator", "TaskContext", "TaskContextManager", "AutonomyLimits", "ScreenElement", "ScreenObservation", "ScreenUnderstandingProvider"]

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
