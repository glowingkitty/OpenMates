# contract-test-file: supporting surface=rest_api assertions=focus-modes.phases,focus-modes.full-instruction,focus-modes.history-events
"""Phase gates test user-visible behavior without real provider or storage side effects."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from backend.shared.python_schemas.app_metadata_schemas import AppFocusDefinition
from backend.shared.python_utils.focus_mode_skill_loader import (
    load_focus_mode_from_skill_md,
    SkillMdParseError,
)
from backend.shared.providers.typesafe.models import DecisionResponse, ChoiceAnswer
from backend.apps.ai.processing.focus_phases import (
    FocusPhaseRuntime,
    restore_state,
    phase_prompt,
    evaluate_boundary,
    parse_project_phase_focus,
)


def focus():
    return AppFocusDefinition(
        id="sample",
        name_translation_key="sample",
        description_translation_key="sample",
        system_prompt="Global private instructions.",
        phases_version=1,
        phases=[
            {
                "id": "clarify",
                "title": "Understand",
                "instructions": "Ask five questions by default; honor skip or all-at-once.",
                "requirements": [
                    {
                        "id": "understood",
                        "text": "Enough context or explicit request to proceed.",
                    }
                ],
            },
            {
                "id": "confirm",
                "title": "Confirm profile",
                "instructions": "PRIVATE_SECOND_PHASE_INSTRUCTION",
                "requirements": [
                    {
                        "id": "approval",
                        "type": "user_confirmation",
                        "text": "The user approves the profile.",
                    }
                ],
            },
            {
                "id": "deliver",
                "title": "Deliver",
                "instructions": "PRIVATE_LAST_PHASE_INSTRUCTION",
                "requirements": [
                    {"id": "delivered", "text": "The requested plan is delivered."}
                ],
            },
        ],
    )


def state(f=None):
    return restore_state(f or focus(), focus_id="jobs-sample", chat_id="chat-a")


def evaluator(choices=None, confidence=1):
    async def decide(**kwargs):
        return DecisionResponse(
            model="test",
            answers={
                key: ChoiceAnswer(
                    type="choice",
                    choice=(choices or {}).get(
                        key,
                        "met"
                        if key.startswith("requirement_")
                        else "none"
                        if key == "rewind"
                        else "no",
                    ),
                    confidence=confidence,
                    probabilities={
                        choice: 1
                        if choice
                        == (choices or {}).get(
                            key,
                            "met"
                            if key.startswith("requirement_")
                            else "none"
                            if key == "rewind"
                            else "no",
                        )
                        else 0
                        for choice in question["criteria"]
                    },
                )
                for key, question in kwargs["questions"].items()
            },
        )

    return decide


def evaluate(
    s,
    boundary="user",
    choices=None,
    confidence=1,
    turn="turn-1",
    boundary_id="boundary-1",
):
    return asyncio.run(
        evaluate_boundary(
            focus(),
            s,
            boundary=boundary,
            boundary_id=boundary_id,
            turn_id=turn,
            latest_user="Skip remaining questions and proceed.",
            messages=[{"role": "user", "content": "Proceed."}],
            secrets_manager=None,
            evaluator=evaluator(choices, confidence),
        )
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_prompt_includes_only_current_instructions_and_other_titles():
    prompt = phase_prompt(focus(), state())
    assert "Global private instructions." in prompt and "Ask five questions" in prompt
    assert "Confirm profile" in prompt and "Deliver" in prompt
    assert (
        "PRIVATE_SECOND_PHASE_INSTRUCTION" not in prompt
        and "PRIVATE_LAST_PHASE_INSTRUCTION" not in prompt
    )
    assert "Enough context" in prompt


@pytest.mark.parametrize(
    "decision,confidence", [("unmet", 1), ("unsure", 1), ("met", 0.1)]
)
# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_unmet_uncertain_or_low_confidence_never_advances(decision, confidence):
    s = state()
    assert (
        evaluate(s, choices={"requirement_understood": decision}, confidence=confidence)
        == s
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_user_skip_can_advance_with_one_response_without_question_count():
    result = evaluate(state())
    assert result.phase_id == "confirm" and result.version == 1
    assert result.transitions[0]["type"] == "focus_phase_changed"
    assert (
        "instructions" not in result.transitions[0]
        and "requirements" not in result.transitions[0]
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_outstanding_question_blocks_tool_or_assistant_boundary():
    for boundary in ("tools", "assistant"):
        s = state()
        assert evaluate(s, boundary, {"awaiting_user": "yes"}) == s


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_confirmation_gate_blocks_assistant_approval_claims():
    s = evaluate(state())
    assert (
        evaluate(
            s,
            "assistant",
            {"requirement_approval": "unmet"},
            turn="turn-2",
            boundary_id="boundary-2",
        )
        == s
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_earlier_phase_consent_cannot_auto_approve_new_phase_in_same_turn():
    entered = evaluate(state(), turn="turn-1")
    assert entered.phase_id == "confirm"
    assert (
        evaluate(entered, "assistant", turn="turn-1", boundary_id="assistant-1")
        == entered
    )
    assert (
        evaluate(entered, "user", turn="turn-2", boundary_id="user-2").phase_id
        == "deliver"
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_rewind_changes_phase_and_does_not_bounce_forward_in_same_turn():
    s = evaluate(evaluate(state()), turn="turn-2", boundary_id="boundary-2")
    assert s.phase_id == "deliver"
    result = evaluate(
        s, choices={"rewind": "clarify"}, turn="turn-3", boundary_id="boundary-3"
    )
    assert (
        result.phase_id == "clarify"
        and result.transitions[-1]["direction"] == "backward"
    )
    assert (
        evaluate(result, "assistant", turn="turn-3", boundary_id="boundary-4") == result
    )
    assert (
        evaluate(result, turn="turn-4", boundary_id="boundary-5").phase_id == "confirm"
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_duplicate_boundary_never_switches_twice():
    s = evaluate(state())
    assert evaluate(s) == s


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_final_completion_preserves_focus_and_allows_later_rewind():
    s = evaluate(evaluate(state()), turn="turn-2", boundary_id="boundary-2")
    completed = evaluate(s, "assistant", turn="turn-3", boundary_id="boundary-3")
    assert (
        completed.complete
        and completed.phase_id == "deliver"
        and completed.focus_id == s.focus_id
    )
    assert len(completed.transitions) == 2
    assert (
        evaluate(
            completed,
            choices={"rewind": "confirm"},
            turn="turn-4",
            boundary_id="boundary-4",
        ).phase_id
        == "confirm"
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_changed_definition_or_wrong_chat_does_not_restore_old_progress():
    s = evaluate(state())
    assert (
        restore_state(
            focus(), focus_id=s.focus_id, chat_id="different", saved=s.model_dump()
        ).phase_id
        == "clarify"
    )
    f = focus()
    f.phases[0].instructions += " Revision."
    assert (
        restore_state(
            f, focus_id=s.focus_id, chat_id=s.chat_id, saved=s.model_dump()
        ).run_id
        != s.run_id
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_project_text_uses_same_schema_and_global_instruction():
    instruction = "---\nphases_version: 1\nphases:\n  - id: understand\n    title: Understand\n    instructions: Ask one question.\n    requirements:\n      - id: understood\n        text: The goal is clear.\n---\nProject global rules."
    f = parse_project_phase_focus(instruction, "project-focus")
    assert (
        f.phases[0].title == "Understand" and f.system_prompt == "Project global rules."
    )
    assert parse_project_phase_focus("Legacy plain text", "project-focus") is None


@pytest.mark.parametrize(
    "problem",
    ["duplicate_phase", "duplicate_requirement", "unknown_field", "wrong_version"],
)
# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_invalid_definition_fails_closed(problem):
    value = focus().model_dump(by_alias=False)
    if problem == "duplicate_phase":
        value["phases"].append(value["phases"][0])
    if problem == "duplicate_requirement":
        value["phases"][0]["requirements"].append(value["phases"][0]["requirements"][0])
    if problem == "unknown_field":
        value["phases"][0]["minimum_questions"] = 5
    if problem == "wrong_version":
        value["phases_version"] = 2
    with pytest.raises(ValidationError):
        AppFocusDefinition.model_validate(value)


@pytest.mark.parametrize(
    "yaml_text", ["id: sample\nid: other", "id: sample\nphases: &p []\nother: *p"]
)
# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_ambiguous_yaml_fails_closed(tmp_path, yaml_text):
    source = tmp_path / "SKILL.md"
    source.write_text("---\n" + yaml_text + "\n---\n## System prompt\nLegacy prompt")
    with pytest.raises(SkillMdParseError):
        load_focus_mode_from_skill_md(str(source), "jobs")


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_provider_failure_retains_phase():
    async def failed(**kwargs):
        raise TimeoutError()

    s = state()
    result = asyncio.run(
        evaluate_boundary(
            focus(),
            s,
            boundary="user",
            boundary_id="b",
            turn_id="t",
            latest_user="Proceed",
            messages=[],
            secrets_manager=None,
            evaluator=failed,
        )
    )
    assert result == s


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_late_decision_cannot_overwrite_newer_run():
    class Redis:
        value = None

        async def get(self, key):
            return self.value

        async def eval(self, script, n, key, old, new):
            if (self.value or "") != old:
                return 0
            self.value = new
            return 1

    async def run():
        redis = Redis()
        runtime = FocusPhaseRuntime(focus(), state(), redis=redis, owner_id="owner")
        await runtime.load()
        redis.value = json.dumps({"newer_run": True})
        changed = await runtime.evaluate(
            boundary="user",
            boundary_id="b",
            turn_id="t",
            latest_user="Proceed",
            messages=[],
            secrets_manager=None,
            evaluator=evaluator(),
        )
        assert not changed and runtime.state.phase_id == "clarify"
        assert json.loads(redis.value) == {"newer_run": True}

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_replayed_unmet_boundary_is_evaluated_only_once():
    calls = []

    async def unmet(**kwargs):
        calls.append(kwargs)
        return await evaluator({"requirement_understood": "unmet"})(**kwargs)

    async def run():
        runtime = FocusPhaseRuntime(focus(), state())
        args = dict(
            boundary="user",
            boundary_id="same-user-message",
            turn_id="turn-1",
            latest_user="I need more time",
            messages=[],
            secrets_manager=None,
            evaluator=unmet,
        )
        assert not await runtime.evaluate(**args)
        assert not await runtime.evaluate(**args)
        assert runtime.state.phase_id == "clarify" and runtime.state.version == 0
        assert len(calls) == 1

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=focus-modes.phases
def test_career_pilot_is_phased_and_user_overridable():
    root = Path(__file__).resolve().parents[2]
    f = AppFocusDefinition.model_validate(
        load_focus_mode_from_skill_md(
            str(root / "backend/apps/jobs/focus_modes/career-insights/SKILL.md"), "jobs"
        )
    )
    assert [p.id for p in f.phases] == [
        "understand",
        "confirm_profile",
        "explore",
        "next_steps",
    ]
    assert (
        "five" in f.phases[0].instructions
        and "skip remaining" in f.phases[0].instructions
    )
    assert all("five" not in r.text for p in f.phases for r in p.requirements)


# contract-test: supporting surface=rest_api assertions=focus-modes.phases,focus-modes.full-instruction
@pytest.mark.parametrize("assigned_apps", [None, ["web"], []])
@pytest.mark.parametrize("project", [False, True])
def test_main_transition_preserves_mate_permissions_and_recovery_prompt(assigned_apps, project):
    """Execute the actual processor transition helper with a real phase runtime.

    Only tool generation/selection are replaced; the platform phase decision,
    prompt refresh, permission inputs and tool merge execute production code.
    This supporting check does not replace real multi-message inference.
    """
    import ast
    from types import SimpleNamespace
    from backend.apps.ai.processing.project_file_tools import build_project_focus_prompt

    class Runtime(FocusPhaseRuntime):
        async def evaluate(self, **kwargs):
            return await super().evaluate(**kwargs, evaluator=evaluator())

    f = focus().model_copy(update={"allowed_apps": ["jobs"]})
    focus_id = "project-sample" if project else "jobs-sample"
    runtime = Runtime(f, restore_state(f, focus_id=focus_id, chat_id="chat-a"))
    request = SimpleNamespace(active_focus_id=None if project else focus_id,
                              message_id="turn-1", current_user_content="Skip remaining questions and proceed.")
    project_focus = {"focus_id": focus_id, "project_id": "project-a", "name": "Sample",
                     "instruction": phase_prompt(f, runtime.state)} if project else None
    old_section = (build_project_focus_prompt(project_focus, []) if project else
                   f"--- Active Focus: {focus_id} ---\n{phase_prompt(f, runtime.state)}\n--- End Active Focus ---")
    generated = []

    def generate(**kwargs):
        # The production generator interprets [] as all apps. An explicit empty
        # Mate allowlist must avoid invoking it, rather than widening that scope.
        apps = kwargs["assigned_app_ids"]
        assert apps != []
        permitted = set(kwargs["discovered_apps_metadata"]) if apps is None else set(apps)
        generated.append(permitted)
        return [{"function": {"name": app + "-search"}} for app in permitted]

    async def select(**kwargs):
        assert "PRIVATE_SECOND_PHASE_INSTRUCTION" in kwargs["phase_instructions"]
        return kwargs["candidates"]

    source = Path(__file__).parents[1] / "apps/ai/processing/main_processor.py"
    tree = ast.parse(source.read_text())
    processor = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name == "handle_main_processing")
    helper = next(n for n in processor.body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "evaluate_active_phases")
    wrapper = ast.parse("""async def exercise(full_system_prompt, answer_recovery_system_prompt,
            active_focus_prompt_section, project_phase_prompt_section,
            available_tools_for_llm, allowed_tool_names):
        pass
        changed = await evaluate_active_phases('user', 'turn-1:user',
            [{'role': 'user', 'content': 'Skip remaining questions and proceed.'}])
        return changed, full_system_prompt, answer_recovery_system_prompt, available_tools_for_llm
""")
    wrapper.body[0].body[0] = helper
    scope = dict(focus_phase_runtimes=[runtime], request_data=request, secrets_manager=None,
        phase_prompt=phase_prompt, active_project_focus=project_focus, active_project_sources=[],
        build_project_focus_prompt=build_project_focus_prompt, user_requested_skills_only=False,
        assigned_app_ids=assigned_apps, discovered_apps_metadata={app: SimpleNamespace(
            skills=[SimpleNamespace(id="search")]) for app in ["web", "code", "jobs"]},
        generate_tools_from_apps=generate, translation_service=None, task_queue_blocks_plan_tools=False,
        reselect_phase_tools=select, _canonicalize_tool_name=lambda name: name,
        task_tool_name_variants=lambda name: {name})
    # Include production initial generation so an empty Mate cannot retain
    # preselected app tools simply because the old generator treats [] as inherit.
    initial = next(n for n in processor.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "available_tools_for_llm" for t in n.targets))
    scope["preselected_skills"] = ["web-search"]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[initial], type_ignores=[])),
                 str(source), "exec"), scope)
    initial_tools = scope["available_tools_for_llm"] + [{"function": {"name": "internal-lifecycle"}}]
    generated.clear()
    exec(compile(ast.fix_missing_locations(wrapper), str(source), "exec"), scope)
    result = asyncio.run(scope["exercise"]("Base\n" + old_section, "Recovery\n" + old_section,
        None if project else old_section, old_section if project else None,
        initial_tools, {t["function"]["name"] for t in initial_tools}))
    changed, prompt, recovery, tools = result
    assert changed and runtime.state.phase_id == "confirm"
    assert request.focus_phase_state[focus_id]["phase_id"] == "confirm"
    assert "PRIVATE_SECOND_PHASE_INSTRUCTION" in prompt
    assert "PRIVATE_SECOND_PHASE_INSTRUCTION" in recovery
    assert "Ask five questions by default; honor skip or all-at-once." not in recovery
    permitted = {"web", "code", "jobs"} if assigned_apps is None else set(assigned_apps)
    assert generated == ([permitted] if permitted else [])
    assert {tool["function"]["name"] for tool in tools} == {
        "internal-lifecycle", *(app + "-search" for app in permitted)}
