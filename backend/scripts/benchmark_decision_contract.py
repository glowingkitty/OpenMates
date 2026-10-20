# contract-test-file: infrastructure
"""Minimal native-choice contract helpers for manual decision benchmarks.
Architecture: pure local functions, with no provider or application dependencies.
Data: benchmark question definitions and parsed provider response dictionaries.
Validation: exact question coverage, finite probabilities, native model identity.
Evaluation: literal choice accuracy; probabilistic loss remains in each harness.
This module performs no I/O, inference, credential access, or routing changes.
"""
from __future__ import annotations

import math


def choice(instructions, criteria):
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def probability(value):
    """Reject booleans and non-finite JSON numbers as probabilities."""
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def validate(data, questions, model):
    if not isinstance(data, dict) or data.get("model") != model:
        raise ValueError("model_identity")
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("answer_coverage")
    usage = data.get("usage")
    tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
    if type(tokens) is not int or tokens < 0:
        raise ValueError("token_usage")
    for key, question in questions.items():
        answer = answers[key]
        if question.get("type") != "choice" or not isinstance(answer, dict) or answer.get("type") != "choice":
            raise ValueError("answer_type")
        probabilities = answer.get("probabilities")
        expected = set(question["criteria"])
        if (not isinstance(probabilities, dict) or set(probabilities) != expected
                or any(not probability(value) for value in probabilities.values())
                or abs(sum(probabilities.values()) - 1) > 0.025):
            raise ValueError("probabilities")
        if not probability(answer.get("confidence")):
            raise ValueError("confidence")
        if answer.get("choice") not in expected:
            raise ValueError("choice_value")
    return answers, tokens


def evaluate(answers, expected):
    """Return choice checks in the prior benchmark's compact receipt shape."""
    checks = {}
    for key, label in expected.items():
        answer = answers[key]
        actual = answer["choice"]
        checks[key] = {"expected": label, "actual": actual, "correct": actual == label,
                       "confidence": answer["confidence"],
                       "expected_probability": answer["probabilities"][label]}
    return checks, []
