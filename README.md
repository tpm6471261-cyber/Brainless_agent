# Brainless Agent

Brainless Agent is a Python computer-use runtime. It orchestrates a real, persistent Chrome session and uses chatbot **websites** as interchangeable reasoning engines. It does not call OpenAI, Gemini, Anthropic, or another model reasoning API. The optional AssemblyAI key is used only for speech transcription and never grants reasoning or execution authority.

## vNext autonomous computer-agent runtime

Alongside the existing browser-provider workflow, vNext adds a runtime-owned autonomous execution path:

```text
USER -> Root -> capability analysis -> AgentRegistry -> reuse | AgentFactory
     -> AgentSupervisor/ActionRuntime -> observe -> structured decision -> policy/permission
     -> resource lock -> controller action -> observe and verify -> audited result
```

`app/autonomy` is model independent: a decision provider can propose only a typed `ComputerAction`; it cannot access Python, the OS, controller backends, permissions, or tool registration. `ActionRuntime` validates identity, allow-listed tool, permission, global policy, arguments, locks shared resources, executes through a replaceable `ComputerController`, observes again, and verifies expected state. Failures are machine-readable (`PERMISSION_DENIED`, `CAPABILITY_UNAVAILABLE`, `VERIFICATION_FAILED`, and related codes), bounded by step and failure budgets, and logged in runtime audit records.

The production `PlaywrightComputerController` implements real browser observation/navigation and explicitly reports unsupported OS capabilities rather than faking success. OS/browser/filesystem/process adapters remain behind `ToolRegistry`; platform-specific controllers can be added without changing the agent hierarchy. The integration tests use an injected deterministic controller solely to make the full runtime flow reproducible; production actions are never hard-coded workflows.

Agents are configurations, not fixed classes. `CapabilityAnalyzer` derives conservative minimum requirements, `AgentRegistry` reuses an idle compatible agent, and `AgentFactory` validates an `AgentSpec`, parent permission boundary, and registered tool metadata before creation. Parent-owned grants remain the only way to add permissions. `ResourceLockManager` serializes mouse/keyboard/browser/screen resources. Existing `AgentManager` continues to supply hierarchy, lifecycle, pause/resume/retry/termination, parallel independent execution, and persisted event auditing.

### Autonomous runtime test coverage

`tests/test_autonomous_runtime.py` proves dynamic BrowserAgent creation, least-privilege navigation, observation/action verification, registry reuse, denied mouse control, authorized parent grant, and task requirement analysis. Browser, OS, and provider integrations still require the local platform and an owner-authenticated profile.

## Phase 1: working vertical slice

The current implementation is an end-to-end browser-driven MVP:

1. Opens a persistent, visible Chrome profile with Playwright.
2. Navigates to ChatGPT (or selects Gemini/Claude when named in a task).
3. Locates the webpage's semantic prompt element, writes and submits a rendered prompt.
4. Observes generation controls, extracts the rendered assistant response from the DOM, validates it is not empty, prints it, and stores it locally in SQLite.
5. Runs multiple named providers and asks the selected synthesis provider to compare their labelled responses.
6. Uses a logged runtime state machine, bounded response-extraction recovery, action/time budgets, and a cooperative emergency-stop latch.

The provider interface and adapters are implemented now so the runtime has no provider-specific branches. Gemini and Claude selectors are included, but their current UIs evolve frequently; verify the configured DOM selectors after logging in. The desktop GUI and bounded DOM/clipboard/OCR response-extraction fallbacks are available now. A system-wide emergency hotkey and visual-anchor discovery remain future work.

## Architecture

```text
CLI -> AgentRuntime -> State/Prompt/SQLite Memory -> Provider Registry
    -> Provider Adapter -> BrowserManager -> persistent Chrome -> chatbot website
```

### Hierarchical agents and tools

The runtime also provides a local, typed `AgentManager` for work that benefits from delegation. A root agent creates child agents with an explicit task, narrowly scoped context, permissions, and tool allow-list. Child permissions must be a subset of their parent's permissions; a tool is only invoked after the registry verifies both the allow-list and every required capability. Global policy can auto-approve, require human approval, or deny sensitive capabilities.

```text
USER -> ROOT AGENT -> AGENT MANAGER
                         |- Research child -> browser.read tool
                         |- Coding child   -> explicitly granted tools
                         `- Testing child  -> explicitly granted tools
```

Agent events record task, status, result, error, tool, and permission-denied outcomes. Independent children can run concurrently, and a parent can inspect the tree, collect results, retry bounded failures, pause, resume, or terminate direct children. The provider websites remain the reasoning layer; agent orchestration and tool permissions remain in Python.

The runtime observes after navigation and before sending input. Provider adapters use DOM/accessibility locators instead of fixed screen coordinates. If a login, CAPTCHA, 2FA, or another security challenge is detected, the run stops and tells the user to complete it manually. The project never captures passwords, exports cookies, or attempts to bypass a security mechanism.


## Web Command Center

Run the authenticated, read-mostly operations dashboard with a local token:

```bash
BRAINLESS_DASHBOARD_TOKEN="replace-with-at-least-16-characters" python run_dashboard.py
```

Open `http://127.0.0.1:8765` and enter the same token. The responsive, keyboard-accessible dark operations dashboard renders authoritative mission, task, agent, action, resource, event, world-model, inventory, approval, and component-health projections. Its desktop sidebar collapses into a mobile navigation drawer, dense runtime tables remain horizontally navigable on tablets, and status colors always include readable text labels. Press `/` to focus structured global search. It uses authenticated JSON endpoints (`/api/system`, `/api/health`, `/api/events`, `/api/search`), an SSE replay stream (`/api/stream`), and an authenticated command endpoint (`/api/commands`). It never imports or invokes computer tools. Commands are allow-listed by `RuntimeCommandGateway`, authorized with constant-time token comparison, applied to runtime-owned mission/takeover services, and emitted back as correlated events.

The dashboard event bus retains a bounded 2,000-event in-memory replay window with monotonically increasing sequence IDs and backpressure, backed by retained SQLite event history. Mission, task, agent, action, and trigger history comes from existing durable stores; unsupported health integrations are shown as `unknown` or `not_configured`, never synthesized. On reconnect, the client fetches a fresh authoritative snapshot before requesting events after its last sequence. When a reasoning provider is configured, the standalone command center composes a least-privilege runtime task graph and executes it with `TaskEngineMissionRunner` through `AutonomousTaskEngine`; without a provider, mission execution is accurately reported as `not_configured`.

Runtime agent and action records are incrementally bridged into correlated dashboard events. The Analytics page uses real terminal mission/task, action audit, retry, intervention, agent failure, and approval records. A rate displays `N/A` when no valid denominator exists rather than inventing a score. Mission execution runs in supervised mode: medium/high-risk actions create metadata-only durable approval requests, wait without acquiring resources, and resume only after an authenticated dashboard decision passes through `ApprovalSystem`. Action arguments and sensitive text are never written to the approval store.

The dashboard builds an authoritative task-to-mission index from persisted mission graphs and uses it to correlate agents, action audits, and events that carry only a task ID. Selecting a mission opens a drill-down with its objective, policy, acceptance criteria, constraints, task graph, assigned agents, and correlated event timeline. Correlation is a read-only projection: it never rewrites event, agent, action, or mission records.

`AutonomyGovernor` is the final deterministic mission gate before mode policy, permissions, resources, and tool execution. `RuntimeMissionComposer` registers mission-scoped task IDs and least-privilege contracts containing allowed tools, allowed permissions, forbidden actions, confidence thresholds, and action/failure budgets. High-risk contracted actions require independent approval; exhausted budgets and out-of-contract authority are denied. Mission drill-downs expose the contract and real budget consumption. The reasoning provider cannot register contracts or make governor decisions.

`ActionRuntime` also treats an action ID as single-use for the lifetime of a runtime process. A duplicate delivery returns the original result without acquiring resources or repeating side effects. Restart recovery remains checkpoint-driven: it re-observes and verifies environmental state rather than blindly replaying an action.

Temporary capabilities use `CapabilityLeaseRegistry`. A parent may lease only authority it already possesses, to a direct child, for that child's current task, for at most 24 hours. Tool execution accepts an active matching lease in place of a permanent permission; revocation, expiry, task reassignment, or process restart fails closed. The dashboard shows active lease metadata and expiry times but cannot issue leases.

### Dashboard security and deployment

The server binds to loopback by default. Put it behind an authenticated TLS reverse proxy for remote access and rotate `BRAINLESS_DASHBOARD_TOKEN` operationally. Read endpoints and SSE require the token; mutation requests are schema-limited, size-bounded, authenticated, and routed through the runtime command gateway. Responses add restrictive framing, content-type, referrer, browser-permission, and content-security headers. Sensitive argument and state keys are recursively redacted. The dashboard cannot grant permissions, execute tools, write WorldState, or contact a reasoning provider.

Architecture: `Browser UI -> authenticated dashboard API -> runtime projections/command gateway -> mission/operator policy -> existing validated ActionRuntime`. Runtime events flow back via `AutonomousEventBus -> bounded replay -> SSE -> browser`.

### Voice control with AssemblyAI Streaming v3

Install dependencies, set `ASSEMBLYAI_API_KEY`, and select a bounded activation mode in `.env` or the process environment. Voice is disabled when the key is absent. The default `push_to_talk` mode does not open a microphone automatically; `voice_active` and `voice_session` start a microphone session with the Command Center. Audio is 16 kHz mono PCM16 and is streamed through the AssemblyAI Python SDK's v3 streaming client using `universal-3-5-pro` by default.

```bash
export ASSEMBLYAI_API_KEY="your-key"
export VOICE_MODE="voice_session"
BRAINLESS_DASHBOARD_TOKEN="replace-with-at-least-16-characters" python run_dashboard.py
```

The voice architecture is `Microphone -> AssemblyAI Streaming v3 -> VoiceTurn -> VoiceIntentEngine -> VoiceRuntimeRouter -> AutonomousOperator -> validated mission runtime`. Partial turns update ephemeral dashboard state but never execute. Only deduplicated finalized turns are classified. Ordinary multi-step speech becomes one mission goal for the existing planner; deterministic stop, pause, takeover, status, and approval phrases are routed to existing runtime services. AssemblyAI and the voice service have no ToolRegistry, permission-grant, controller, or WorldState write path.

Speech confidence, intent classification, authorization, and verification are separate decisions. Low-confidence speech waits for repetition. Sensitive language waits for an explicit `yes` or `confirm`, after which the resulting mission still passes through the autonomy governor, approval policy, permissions, scheduler, tools, observation, and verification. A spoken `approve` or `deny` resolves an approval only when exactly one pending runtime approval exists; otherwise the user is directed to the dashboard.

Raw audio is never persisted. Transcript persistence defaults off; durable records contain session/intent/result metadata and `[NOT STORED]` in persisted event transcripts. If enabled, transcript storage is bounded and recursively redacts credential-like content. Session duration, idle timeout, reconnect count, language, confidence thresholds, transcript retention behavior, and model are environment-configurable. Connections use bounded exponential backoff and are explicitly terminated during runtime shutdown. The Voice dashboard shows the ephemeral live transcript, last finalized turn, connection/session state, active mission, bounded command history, confidence, errors, and real session metrics.

Troubleshooting: `not_configured` means no API key was supplied; `disconnected` indicates no active bounded session; microphone failures require an OS input device and the SDK's audio extras. Keep `VOICE_STORE_AUDIO=false`—the implementation rejects raw-audio persistence. For cost control, prefer push-to-talk or a bounded voice session instead of continuous mode.

The Voice page also supports runtime-only credential setup: select **Configure AssemblyAI**, enter the key in the password field, and then hold **Hold to talk**. This authenticated command is handled by the same runtime gateway as other dashboard controls. The key is validated, passed through a write-only control plane, and retained only inside the in-memory AssemblyAI client configuration; snapshots, responses, SSE events, audit details, and the voice metadata store never contain it. Restarting the process clears a dashboard-supplied key. Use `ASSEMBLYAI_API_KEY` when durable deployment configuration is required, and use a TLS reverse proxy before accessing the dashboard remotely because the built-in server intentionally binds plain HTTP to loopback.

### Multimodal perception architecture

The runtime now has an on-demand `MultimodalPerceptionEngine` above the existing computer controller observation boundary:

```text
Voice / authenticated dashboard / agent request
                    |
             PerceptionRequest + capability scope
                    |
 Controller / accessibility / DOM / visual providers
                    |
        immutable PerceptionObservation records
                    |
             PerceptionFusionEngine
                    |
             EnvironmentSnapshot
                    |
       WorldStateManager + structural events
                    |
       semantic grounding -> proposed action
                    |
 governor -> policy -> permission -> tool -> execution
                    |
             observation -> verification
```

`PerceptionSource` is provider-independent. The production launcher currently installs `ComputerControllerSource`, which adapts the real active controller's read-only `observe()` method; accessibility, DOM, OCR, or visual-understanding adapters can be registered when their platform integration is available. Missing sources and screenshots are reported as unavailable rather than fabricated. Agent requests are checked against permissions held by the authoritative `AgentManager`, and fields outside the requested capability scope are removed before fusion. The engine serializes observations to avoid stale-state races, continues in a visible `degraded` state when one of several sources fails, records observed application/window/browser/UI identifiers in the existing `WorldStateManager`, measures actual perception latency, and emits structural `environment_observed`, drift, `perception_source_failed`, and `human_required` events. Capture is active and on demand rather than an unconditional screenshot loop.

`ScreenGroundingEngine` resolves text, roles, ordinals, and spatial relationships against `UIElement` records. Accessibility and DOM evidence outrank application, OCR, visual, and controller-text evidence. A coordinate is derived only from the selected semantic element's current bounds; an unresolved or equally ranked ambiguous target fails closed. Existing `TargetResolver.resolve()` remains backward compatible, while `resolve_environment()` uses normalized multimodal state.

Observed webpage, DOM, OCR, voice-context, and screenshot content is always labelled **untrusted observation data**. `MultimodalCommand` rejects screen-originated executable intent, and `ContextBuilder` sends only bounded relevant elements and history. Perception providers have no execution method, tool registry, permission mutation, or agent factory. Shared redaction removes credential-bearing keys and values from dashboard projections, events, and durable voice metadata. CAPTCHA, MFA, security-key, biometric, identity, and payment-confirmation indicators emit `human_required` and enter user-takeover mode; no bypass is attempted.

The dashboard **Perception** page provides an authenticated **Observe now** control, real source/latency/confidence counts, active application/window/browser state, structured UI elements, and the `OBSERVE → UNDERSTAND → TARGET → ACTION → OBSERVE → VERIFY` trace. The browser receives projections only and cannot capture a screen or invoke a controller directly. Filesystem paths backing screenshots are never projected; image retrieval is separately authenticated, restricted to the runtime's `screenshots` and `data` roots, size bounded, and marked `no-store`.

Voice approval fails closed by default because speech transcription does not establish speaker identity. Spoken approval can be enabled only by injecting an independent `approval_authorizer`; otherwise the runtime directs the user to the authenticated approval center. Voice configuration also rejects non-finite confidence values and unbounded session settings. Microphone and AssemblyAI teardown failures still produce a clean stopped state, and a paused or disconnected push-to-talk session can reconnect without leaving a zombie listener.

### Automation readiness guarantees

Explicitly paused missions are inert: background events cannot re-observe or restart them until an authenticated dashboard or authorized voice-resume transition changes them back to `waiting`. The operator dispatches consumed runtime events to the persisted trigger engine, so event and mission triggers share the same authoritative event path instead of relying on a second polling implementation. A voice resume both releases takeover and emits mission wakeups for paused user-blocked work.

Event details are redacted before entering either the in-memory history or SQLite event store. Action arguments, outputs, errors, mission failure checkpoints, voice records, and dashboard projections use the same credential-aware redaction boundary, preventing observed password/token material from being fed back to a reasoning provider through action results. This redaction complements—rather than replaces—tool permissions, policy, approvals, mission contracts, and verification.

## Installation

For a complete Hinglish setup guide—including virtual environments, dashboard/voice configuration, persistent Google Chrome login, automation checklist, and troubleshooting—see [`run_project.md`](run_project.md).

Requires Python 3.11+ and an installed Google Chrome/Chrome-compatible browser.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
playwright install chromium
```

`channel: chrome` in `app/config/providers.yaml` asks Playwright for the installed Chrome channel. If Chrome is not installed, install it or change the channel to a supported locally installed browser.

## First-run Chrome setup

Run the application once, let the visible Chrome window open, and manually sign in to the service(s) you own. The profile is retained at `data/browser-profile`; it is local-only and gitignored. Do not point it at a profile that is currently open in another Chrome process. Do not put credentials in this repository.

## Run

```bash
python run.py
```

### Desktop UI

Run `python run_gui.py` to launch the Tk desktop UI. It provides a task editor, provider checkboxes, strategy and prompt-profile selectors, Start, cooperative Pause/Resume, Emergency Stop, current status, an in-window result/error log, and a refreshable local task-history table. The browser closes after each GUI run while the persistent profile remains for the next run. Pause takes effect at the next action boundary. Emergency Stop cancels the in-flight browser operation and records the failure state; it does not bypass, dismiss, or otherwise alter provider security pages.

When a provider shows login, CAPTCHA, 2FA, or another security challenge, Brainless pauses without attempting a bypass. Complete the challenge yourself, then press **Continue after login** in the GUI or Enter in the CLI; the runtime verifies the page again before it sends a prompt.

At the prompt, enter a task such as:

```text
Research resilient browser automation patterns.
```

Mentioning more than one configured provider (for example, `compare chatgpt and gemini`) activates deterministic multi-provider task parsing. In the desktop UI, selecting more than one provider also creates a multi-provider workflow when Strategy is **automatic**. The runtime collects labelled answers and sends them to its selected synthesis provider (ChatGPT when selected, otherwise the first selected provider) for a final result.

## Configuration and prompts

Provider URLs, persistent profile location, browser behavior, and bounded runtime limits are in `app/config/providers.yaml`. Prompt templates live in `prompts/<profile>/default.txt`; an optional `prompts/<profile>/<provider>.txt` overrides the default for one provider. Templates support `{task}`, `{previous_results}`, `{provider}`, `{context}`, and `{requirements}`. The runtime retrieves bounded, keyword-matched local context before the first provider prompt. The parser deterministically selects `research`, `coding`, or `analysis` today.

## Adding a provider

Create an adapter subclass of `ChatbotProvider`, give it webpage input/response/stop selectors, and add it to `ProviderRegistry.from_settings`. The agent runtime does not need to change. Test it against the provider's normal browser UI while logged into your own account.

## Local memory

Each completed or failed provider interaction is recorded in `data/memory.db` with task ID, timestamp, provider, prompt, response/status, duration, workflow, errors, and a screenshot path when capture succeeds. Existing databases are migrated in place to add screenshot metadata. `SQLiteMemory.search()` provides local keyword retrieval for later prompt context; no task content is sent to an API by this program.

## Safety and troubleshooting

* You retain control of the visible browser. Stop the process with `Ctrl+C`; the persistent browser context closes cleanly.
* Complete login, CAPTCHA, and 2FA manually. The runtime will not bypass them.
* If an input is not found, inspect the provider website after login and update the adapter selector list. Website DOMs can change.
* Browser actions are bounded by config timeouts and recovery retries; failures are recorded in SQLite.

## Roadmap

Normal response extraction is DOM-first. If its bounded recovery fails, the runtime tries the provider's visible response Copy control plus the local clipboard, then uses local OCR on a recorded screenshot. Every candidate is validated before it can be persisted. OCR requires the optional local Tesseract executable in addition to the Python dependencies.

Next phases add authenticated browser integration tests, provider-specific selector maintenance, visual-anchor discovery, a global emergency hotkey, and task-history controls in the desktop UI.

## Tests

```bash
pytest
```

These tests cover configuration, prompt rendering, local SQLite memory, state transitions, bounded recovery, provider registry behavior, and deterministic task parsing. Browser UI automation remains a manual integration test because it requires the owner's logged-in Chrome session.

### Verified autonomy building blocks

The autonomous runtime now maintains a versioned `WorldStateManager`. Controller observations become evidence-backed facts marked **observed**, **inferred**, **assumed**, or **stale**; tool return values do not update the world model. `ActionContract` optionally supplies runtime-checked preconditions, expected observed effects, retry idempotency, risk metadata, and rollback information. `TargetResolver` is provider-based and uses observed text only as a confidence-scored fallback, never blindly preferring coordinates.

`TaskGraph` and `TaskScheduler` provide validated dependencies, conflict-aware runnable selection, retries, cancellation states, and safe replanning primitives. `ResourceLockManager` uses globally ordered locks, bounded waits, inspectable ownership, and failure cleanup. `CheckpointStore` writes atomically and intentionally requires a fresh environment observation before a resumed action can be executed. `RecoveryEngine` classifies permission, verification, and validation failures and refuses blind retry of non-idempotent actions.

### Task-graph execution and recovery

`AutonomousTaskEngine.run_graph()` executes a validated, mutable dependency graph through the existing agent factory/registry and `ActionRuntime`. It only schedules dependency-ready, non-conflicting work, keeps partial/blocked results explicit, and evaluates supplied `GoalCriterion` acceptance criteria after the graph finishes. The backward-compatible `run()` path is retained for current callers.

Planning context is deliberately scoped: `TaskContextManager` supplies only observed facts and declared permissions to child work; external webpage/document content remains labelled untrusted data and cannot change policy, permissions, identity, or tool grants. `PlanValidator` rejects cyclic graphs, unavailable capabilities/permissions/tools, missing action contracts, and ungated high-risk tasks before execution.

Contracts can set an execution timeout and retry idempotency. A safe retry is always preceded by a fresh controller observation; non-idempotent verification failures select re-observation rather than repeating the action. Checkpoint resumption likewise calls an observer before returning pending work and never replays actions by itself.

`ActionRuntime` writes structured action/observation/verification journal records when given the existing SQLite journal store. `AutonomousTaskEngine` can receive a `CheckpointStore`; it snapshots graph status, retries, agent permissions/statuses, WorldState values, resource ownership, and pending nodes at plan creation and after each task transition. Restart code must call `CheckpointStore.resume(observer)`, which returns a newly observed environment alongside pending work rather than replaying an action.

### Controlled experience and skills

`app.learning` is a durable, advisory layer separate from execution. `ExperienceMemory` stores only structured runtime or human-approved execution outcomes and rejects externally sourced content; retrieval ranks goal/task/environment overlap and treats results as planning suggestions. `SkillRegistry` keeps versioned workflow definitions candidate-first: a skill cannot be registered as verified/trusted, and `SkillEvaluator` can reject a regressing candidate without changing the previous verified version. `WorkflowSynthesizer` turns discovered skills into a `TaskGraph`; the existing plan validator and action runtime remain responsible for permissions, contracts, resources, approval, execution, and verification.

`LearningCoordinator` is the integration point for the experience-to-workflow loop: it persistently records verified runtime outcomes, produces candidate skills only from reusable structured workflows, then retrieves experience and verified skills for a later related goal. `SkillSandbox` statically validates candidate workflow permissions, capabilities, tools, contracts, and high-risk approval requirements with the existing `PlanValidator`; it cannot execute a skill or activate it.
