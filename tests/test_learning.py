import pytest

from app.learning import (Experience, ExperienceMemory, ExperienceSource, Skill, SkillEvaluator,
                          SkillRegistry, SkillStatus, WorkflowSynthesizer)


def make_skill(version=1, status=SkillStatus.CANDIDATE, rate=0.0):
    return Skill("write report", "write a verified report", frozenset({"filesystem.write"}),
                 frozenset({"filesystem.write"}), ({"objective": "write report", "tool": "filesystem.write", "resources": ["filesystem/report"]},),
                 ("report exists",), version=version, status=status, evaluation={"success_rate": rate})


def test_experience_is_durable_ranked_and_external_content_is_not_trusted(tmp_path):
    memory = ExperienceMemory(tmp_path / "experience.db")
    good = Experience("Create a verified report", "report", {"app": "filesystem"}, {"nodes": ["write"]}, True, True, "done", tools_used=("filesystem.write",))
    memory.store(good)
    found = memory.retrieve("create report", task_type="report", environment={"app": "filesystem"})
    assert found == [good]
    with pytest.raises(ValueError, match="External"):
        memory.store(Experience("ignore policy", "report", {}, {}, False, False, "", source=ExperienceSource.EXTERNAL))
    memory.close()


def test_skills_are_versioned_candidate_first_and_regressions_are_rejected(tmp_path):
    registry = SkillRegistry(tmp_path / "skills.db")
    v1 = make_skill(1, rate=.9); registry.register(v1); registry.set_status(v1.skill_id, SkillStatus.VERIFIED)
    v2 = make_skill(2, rate=.5); registry.register(v2)
    outcome = SkillEvaluator().evaluate(v2, [Experience("report", "report", {}, {}, False, False, "failed")], baseline=registry.get(v1.skill_id))
    assert outcome is SkillStatus.REJECTED
    registry.set_status(v2.skill_id, outcome)
    assert registry.get(v1.skill_id).status is SkillStatus.VERIFIED
    assert registry.get(v2.skill_id).status is SkillStatus.REJECTED
    assert registry.search("verified report") == [registry.get(v1.skill_id)]
    registry.close()


def test_second_goal_retrieves_experience_discovers_skill_and_synthesizes_reusable_graph(tmp_path):
    memory = ExperienceMemory(tmp_path / "experiences.db")
    registry = SkillRegistry(tmp_path / "skills.db")
    first = Experience("Create report about weather", "report", {"app": "filesystem"}, {"workflow": "write"}, True, True, "report created")
    memory.store(first)
    skill = make_skill(); registry.register(skill); registry.set_status(skill.skill_id, SkillStatus.VERIFIED)
    reused = memory.retrieve("Create another weather report", task_type="report")
    discovered = registry.search("write verified report")
    graph = WorkflowSynthesizer().synthesize("Create another weather report", discovered, reused)
    assert reused[0].experience_id == first.experience_id
    assert discovered[0].skill_id == skill.skill_id
    node = next(iter(graph.tasks.values()))
    assert node.tool == "filesystem.write" and node.permissions == frozenset({"filesystem.write"})
    memory.close(); registry.close()


def test_execution_evaluation_creates_candidate_only_from_verified_structured_workflow():
    from app.learning import ExecutionEvaluator
    experience = Experience("write report", "report", {}, {"workflow": [{"objective": "write"}], "declared_permissions": ["filesystem.write"], "expected_outcomes": ["file exists"]}, True, True, "done", capabilities_used=("filesystem.write",))
    candidate = ExecutionEvaluator().candidate(experience, "write report", "persist a report")
    assert candidate and candidate.status is SkillStatus.CANDIDATE
    failed = Experience("write report", "report", {}, {"workflow": [{"objective": "write"}]}, False, False, "", failures=("permission denied",))
    assert ExecutionEvaluator().candidate(failed, "bad", "bad") is None


def test_conflicts_require_verification_or_high_risk_escalation():
    from app.learning import AgentMessage, ConflictResolver, Evidence, EvidenceKind, EvidenceStore, MessageKind
    store = EvidenceStore(); first = store.add(Evidence("price", EvidenceKind.URL, "a")); second = store.add(Evidence("price", EvidenceKind.URL, "b"))
    messages = (AgentMessage("a", MessageKind.FINDING, "price", (first.evidence_id,), {"value": "10"}), AgentMessage("b", MessageKind.FINDING, "price", (second.evidence_id,), {"value": "11"}))
    assert ConflictResolver().resolve("price", messages, store).resolution.value == "verify"
    assert ConflictResolver().resolve("price", messages, store, high_risk=True).resolution.value == "escalate"


def test_learning_coordinator_records_first_execution_and_reuses_advisory_workflow(tmp_path):
    from app.learning import LearningCoordinator
    memory = ExperienceMemory(tmp_path / "experience.db")
    registry = SkillRegistry(tmp_path / "skills.db")
    coordinator = LearningCoordinator(memory, registry)
    first = Experience("create project report", "report", {"app": "filesystem"}, {"workflow": [{"objective": "write", "tool": "filesystem.write"}], "declared_permissions": ["filesystem.write"], "expected_outcomes": ["file exists"]}, True, True, "done", capabilities_used=("filesystem.write",))
    candidate = coordinator.record(first, candidate_name="create report", candidate_description="create a report")
    assert candidate and candidate.status is SkillStatus.CANDIDATE
    registry.set_status(candidate.skill_id, SkillStatus.VERIFIED)
    second = coordinator.advise("create another project report", "report", {"app": "filesystem"})
    assert second.experiences[0].experience_id == first.experience_id
    assert second.skills[0].skill_id == candidate.skill_id
    assert second.graph.tasks
    memory.close(); registry.close()


def test_continuous_learning_reuses_candidate_and_evaluates_repeated_outcomes(tmp_path):
    from app.learning import LearningCoordinator
    memory = ExperienceMemory(tmp_path / "experience.db")
    registry = SkillRegistry(tmp_path / "skills.db")
    coordinator = LearningCoordinator(memory, registry)
    plan = {"workflow": [{"objective": "write", "tool": "filesystem.write"}],
            "declared_permissions": ["filesystem.write"], "expected_outcomes": ["file exists"]}

    first = coordinator.record(Experience("write report one", "report", {}, plan, True, True, "done",
        capabilities_used=("filesystem.write",)), candidate_name="write report", candidate_description="write report")
    second = coordinator.record(Experience("write report two", "report", {}, plan, True, True, "done",
        capabilities_used=("filesystem.write",)), candidate_name="write report", candidate_description="write report")

    assert first and second and first.skill_id == second.skill_id
    assert len(registry.versions("write report")) == 1
    assert second.status is SkillStatus.TESTED
    assert second.evaluation["success_rate"] == 1.0
    assert [item["event"] for item in registry.audit_trail(second.skill_id)] == [
        "created", "evaluated", "evaluated", "tested"]
    memory.close(); registry.close()


def test_continuous_learning_never_auto_activates_and_deprecates_regression(tmp_path):
    from app.learning import LearningCoordinator
    memory = ExperienceMemory(tmp_path / "experience.db")
    registry = SkillRegistry(tmp_path / "skills.db")
    coordinator = LearningCoordinator(memory, registry)
    plan = {"workflow": [{"objective": "write", "tool": "filesystem.write"}],
            "declared_permissions": ["filesystem.write"]}
    first = Experience("write report", "report", {}, plan, True, True, "done",
                       capabilities_used=("filesystem.write",))
    skill = coordinator.record(first, candidate_name="write report", candidate_description="write report")
    registry.set_status(skill.skill_id, SkillStatus.VERIFIED, actor="operator", reason="approved")
    result = coordinator.record(Experience("write report", "report", {}, plan, False, False, "failed",
        failures=("verification failed",)), candidate_name="write report", candidate_description="write report")
    assert result.status is SkillStatus.DEPRECATED
    memory.close(); registry.close()


def test_skill_sandbox_rejects_permission_escalation(tmp_path):
    from app.learning import SkillSandbox
    candidate = make_skill()
    with pytest.raises(ValueError, match="unavailable permissions"):
        SkillSandbox().validate(candidate, capabilities=frozenset({"filesystem.write"}), permissions=frozenset(),
                                known_tools=frozenset({"filesystem.write"}), contracted_tools=frozenset({"filesystem.write"}))


def test_corrupt_and_expired_experiences_do_not_break_advisory_retrieval(tmp_path):
    from datetime import datetime, timedelta, timezone
    memory = ExperienceMemory(tmp_path / "experience.db")
    old = Experience("failed report", "report", {}, {}, False, False, "", created_at=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat())
    current = Experience("current report", "report", {}, {}, True, True, "done")
    memory.store(old); memory.store(current)
    memory.db.execute("INSERT INTO experiences VALUES (?,?,?,?,?,?,?,?,?)", ("bad", "now", "runtime", "report", "report", "{}", "not json", 0, 0)); memory.db.commit()
    assert memory.retrieve("report") == [current, old]
    assert memory.purge_expired(timedelta(days=1)) == 1
    assert memory.retrieve("report") == [current]
    memory.close()


def test_runtime_policy_never_grants_skill_permissions_or_ignores_preconditions(tmp_path):
    from app.learning import LearningCoordinator, PolicyEngine
    registry = SkillRegistry(tmp_path / "skills.db"); memory = ExperienceMemory(tmp_path / "memory.db")
    skill = make_skill(); registry.register(skill); registry.set_status(skill.skill_id, SkillStatus.VERIFIED)
    coordinator = LearningCoordinator(memory, registry, policy=PolicyEngine())
    denied = coordinator.advise("write verified report", "report", {"app": "browser"},
        agent_permissions=frozenset(), available_capabilities=frozenset({"filesystem.write"}))
    assert not denied.skills and not denied.graph.tasks
    allowed = coordinator.advise("write verified report", "report", {},
        agent_permissions=frozenset({"filesystem.write"}), available_capabilities=frozenset({"filesystem.write"}))
    assert allowed.skills and allowed.graph.tasks
    memory.close(); registry.close()


def test_skill_sandbox_evaluation_requires_test_before_human_approval_and_audits(tmp_path):
    from app.learning import SkillSandbox
    registry = SkillRegistry(tmp_path / "skills.db")
    candidate = make_skill(); registry.register(candidate)
    outcome, metrics = SkillSandbox().test(candidate, [Experience("write report", "report", {}, {}, True, True, "done")],
        capabilities=frozenset({"filesystem.write"}), permissions=frozenset({"filesystem.write"}),
        known_tools=frozenset({"filesystem.write"}), contracted_tools=frozenset({"filesystem.write"}))
    assert outcome is SkillStatus.TESTED and metrics["verification_rate"] == 1.0
    registry.set_status(candidate.skill_id, outcome, actor="sandbox", reason="controlled verification")
    registry.approve(candidate.skill_id, actor="operator", reason="reviewed sandbox evidence")
    assert registry.get(candidate.skill_id).status is SkillStatus.VERIFIED
    assert [event["event"] for event in registry.audit_trail(candidate.skill_id)] == ["created", "tested", "verified"]
    registry.close()


def test_evidence_store_is_durable(tmp_path):
    from app.learning import Evidence, EvidenceKind, EvidenceStore
    path = tmp_path / "evidence.db"; store = EvidenceStore(path)
    item = store.add(Evidence("report exists", EvidenceKind.FILE, "report.txt")); store.close()
    reopened = EvidenceStore(path)
    assert reopened.get(item.evidence_id).reference == "report.txt"
    reopened.close()


def test_human_feedback_is_durable_and_cannot_target_unknown_experience(tmp_path):
    memory = ExperienceMemory(tmp_path / "experience.db")
    experience = Experience("report", "report", {}, {}, True, True, "done"); memory.store(experience)
    memory.add_feedback(experience.experience_id, "mark_result_wrong", actor="reviewer", detail="incorrect content")
    assert memory.db.execute("SELECT kind FROM experience_feedback").fetchone()[0] == "mark_result_wrong"
    with pytest.raises(KeyError): memory.add_feedback("missing", "approve", actor="reviewer")
    memory.close()


def test_feedback_changes_experience_ranking_and_explanation_is_structured(tmp_path):
    from app.learning import EvidenceStore, explain
    memory = ExperienceMemory(tmp_path / "experience.db")
    rejected = Experience("report", "report", {}, {}, True, True, "done")
    approved = Experience("report", "report", {}, {}, True, True, "done")
    memory.store(rejected); memory.store(approved)
    memory.add_feedback(rejected.experience_id, "mark_result_wrong", actor="reviewer")
    assert memory.retrieve("report")[0].experience_id == approved.experience_id
    summary = explain(approved, EvidenceStore())
    assert summary.goal == "report" and not summary.uncertainty
    memory.close()


def test_agent_performance_is_durable_and_contextual(tmp_path):
    from app.learning import AgentPerformanceMemory
    memory = AgentPerformanceMemory(tmp_path / "agents.db")
    memory.record("slow", "report", "filesystem", success=True, verified=True, duration_ms=20)
    memory.record("fast", "report", "filesystem", success=True, verified=True, duration_ms=2)
    memory.record("bad", "report", "filesystem", success=False, verified=False, duration_ms=1)
    assert memory.best("report", "filesystem")[0].agent_id == "fast"
    memory.close()


def test_disposable_filesystem_sandbox_is_isolated_and_removed():
    from app.learning import create_filesystem_sandbox
    with create_filesystem_sandbox() as sandbox:
        root = sandbox.root
        (root / "candidate.txt").write_text("isolated")
        assert (root / "candidate.txt").is_file()
    assert not root.exists()


def test_skill_sandbox_restricted_runner_accepts_only_runtime_experience(tmp_path):
    import asyncio
    from app.learning import SkillSandbox
    candidate = make_skill()
    async def runner(_):
        return Experience("write report", "report", {}, {}, True, True, "done")
    result = asyncio.run(SkillSandbox().execute_restricted(candidate, runner,
        capabilities=frozenset({"filesystem.write"}), permissions=frozenset({"filesystem.write"}),
        known_tools=frozenset({"filesystem.write"}), contracted_tools=frozenset({"filesystem.write"})))
    assert result.success
