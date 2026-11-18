"""Labelled decision suites for benchmark_gemini_decision_jev.py.

Each module exposes ``cases(private_dir) -> list[dict]`` in the runner's case
format and builds its questions with the production builders, so a benchmark
measures exactly what production asks. Data is synthetic or labelled test data,
never user data; private suites read from ``private_dir`` and return [] without it.
"""

SUITES = (
    "image_safety_prompts",
    "image_safety_images",
    "preprocess_routing",
    "app_focus_routing",
    "voice_turn",
    "prompt_injection",
    "browse_control",
    "postprocess_judge",
    "relevance_judges",
)
