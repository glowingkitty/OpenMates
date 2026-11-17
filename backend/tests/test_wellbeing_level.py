"""Pure wellbeing level math."""


from backend.apps.ai.processing.wellbeing_level import (
    compute_level, sanitize_history, sanitize_scores,
)


# contract-test: direct surface=rest_api assertions=wellbeing-support.hard-negatives
def test_single_dark_joke_stays_zero():
    assert compute_level([], {"suicidal": 0.1, "hopelessness_isolation": 0.15}, now=100).level == 0


# contract-test: direct surface=rest_api assertions=wellbeing-support.rolling-level
def test_drift_raises_to_one_then_two():
    history = []
    levels = []
    for turn in range(8):
        result = compute_level(history, {"hopelessness_isolation": 0.7}, now=turn)
        history = result.updated_history
        levels.append(result.level)
    assert levels[0] == 1 and levels[-1] == 1
    history, levels = [], []
    for turn in range(8):
        result = compute_level(history, {"suicidal": 0.45}, now=turn)
        history = result.updated_history
        levels.append(result.level)
    assert levels[0] == 1 and levels[-1] == 2
    assert compute_level([], {"suicidal": 0.55}, now=1).level == 2


# contract-test: direct surface=rest_api assertions=wellbeing-support.rolling-level
def test_acute_is_immediate_and_needs_plan_with_intent():
    acute = compute_level([], {"plan_or_timeline": 0.8, "suicidal": 0.75}, now=1)
    assert acute.level == 3 and acute.acute
    assert not compute_level([], {"suicidal": 0.9}, now=1).acute
    assert compute_level([], {"danger_from_others": 0.9}, now=1).level == 3


# contract-test: direct surface=rest_api assertions=wellbeing-support.rolling-level
def test_decay_clears_history():
    history = [{"t": 1, "s": {"hopelessness_isolation": 0.5}}]
    for turn in range(6):
        result = compute_level(history, {}, now=10 + turn)
        history = result.updated_history
    assert result.level == 0 and history == []


# contract-test: supporting surface=rest_api assertions=wellbeing-support.rolling-level
def test_history_is_capped_and_dominant_signal_reported():
    history = [{"t": i, "s": {"self_harm": 0.5}} for i in range(8)]
    result = compute_level(history, {"self_harm": 0.5}, now=99)
    assert len(result.updated_history) == 8 and result.dominant_signal == "self_harm"


# contract-test: supporting surface=rest_api assertions=wellbeing-support.rolling-level
def test_malformed_input_is_rejected():
    assert sanitize_scores({"unknown": 0.5}) is None
    assert sanitize_scores({"suicidal": 1.5}) is None
    assert sanitize_scores({"suicidal": float("nan")}) is None
    assert sanitize_scores("x") is None
    assert sanitize_history([{"t": "1", "s": {}}]) is None
    assert sanitize_history([{"t": 1, "s": {}}] * 9) is None
    assert sanitize_history(None) == []
    assert sanitize_history([{"t": 1, "s": {"mania": 0.3}}]) == [{"t": 1, "s": {"mania": 0.3}}]


# contract-test: direct surface=rest_api assertions=wellbeing-support.rolling-level
def test_current_self_injury_with_danger_is_acute():
    result = compute_level([], {"self_harm": 0.95, "self_injury_now": 0.9}, now=1)
    assert result.level == 3 and result.acute
    # high self-harm talk without an injury now stays below acute; so does an injury signal without self-harm
    assert not compute_level([], {"self_harm": 0.95, "self_injury_now": 0.1}, now=1).acute
    assert not compute_level([], {"self_harm": 0.1, "self_injury_now": 0.9}, now=1).acute


# contract-test: direct surface=rest_api assertions=wellbeing-support.rolling-level
def test_hopelessness_alone_never_passes_level_one():
    assert compute_level([], {"hopelessness_isolation": 0.98}, now=1).level == 1
    history, level = [], 0
    for turn in range(8):
        result = compute_level(history, {"hopelessness_isolation": 0.95}, now=turn)
        history, level = result.updated_history, result.level
    assert level == 1
    assert compute_level([], {"hopelessness_isolation": 0.98, "suicidal": 0.9}, now=1).level == 2
