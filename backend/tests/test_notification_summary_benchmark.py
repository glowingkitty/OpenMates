# contract-test-file: infrastructure
# backend/tests/test_notification_summary_benchmark.py
#
# Offline checks of the notification summary benchmark: the synthetic case set
# and the deterministic scoring. No provider is called.
#
# Run: python -m pytest backend/tests/test_notification_summary_benchmark.py -v
from collections import Counter

import pytest

from backend.scripts import benchmark_notification_summary_models as benchmark
from backend.scripts.notification_summary_benchmark_cases import CASES, CASE_BY_ID


def test_case_set_is_synthetic_multilingual_and_covers_the_hard_cases():
    assert len(CASES) >= 95 and all(case.id.startswith('synthetic-') for case in CASES)
    assert {'en', 'de', 'es', 'fr', 'ja'} <= {case.language for case in CASES}
    kinds = Counter(case.id.split('-')[2] for case in CASES)
    assert all(kinds[name] for name in ('done', 'partial', 'question', 'long_question', 'info', 'code'))
    long_question = next(case for case in CASES if '-long_question-' in case.id)
    assert len(long_question.assistant) > 600 and long_question.assistant.rstrip().endswith('?')


def test_scoring_accepts_a_good_summary_and_flags_each_defect():
    case = CASE_BY_ID['synthetic-en-done-1']
    good = benchmark.score_row(case, {'notification_type': 'done', 'notification_summary': 'Added 4 Gemini models, 31 tests pass'})
    assert all(good[key] for key in ('valid', 'type_ok', 'length_ok', 'language_ok', 'facts_ok'))
    wrong_type = benchmark.score_row(case, {'notification_type': 'info', 'notification_summary': 'Added 4 models'})
    assert not wrong_type['type_ok']
    invented = benchmark.score_row(case, {'notification_type': 'done', 'notification_summary': 'Added 9 models'})
    assert not invented['facts_ok']
    too_long = benchmark.score_row(case, {'notification_type': 'done', 'notification_summary': 'x ' * 80})
    assert not too_long['length_ok']
    assert not benchmark.score_row(case, None)['valid']
    assert not benchmark.score_row(case, {'notification_type': 'shout', 'notification_summary': 'Hi'})['valid']


def test_language_oracle_rejects_english_for_german_and_requires_japanese_script():
    german = CASE_BY_ID['synthetic-de-done-1']
    assert not benchmark.score_row(german, {'notification_type': 'done', 'notification_summary': 'Added the models and the tests pass'})['language_ok']
    assert benchmark.score_row(german, {'notification_type': 'done', 'notification_summary': '4 Modelle ergänzt, 31 Tests bestehen'})['language_ok']
    japanese = CASE_BY_ID['synthetic-ja-done-1']
    assert benchmark.score_row(japanese, {'notification_type': 'done', 'notification_summary': '4モデル追加、31件のテスト成功'})['language_ok']
    assert not benchmark.score_row(japanese, {'notification_type': 'done', 'notification_summary': 'Added 4 models'})['language_ok']


def test_summary_reports_reliability_cost_and_latency_per_arm():
    rows = [{'arm': 'gemini-lite', 'availability_status': 'available', 'complete_latency_seconds': 1.0,
             'usage_telemetry': {'raw_usage': {'promptTokenCount': 1000, 'candidatesTokenCount': 100}},
             'score': {'valid': True, 'type_ok': True, 'length_ok': True, 'language_ok': True, 'facts_ok': True}},
            {'arm': 'gemini-lite', 'availability_status': 'available', 'complete_latency_seconds': 3.0,
             'usage_telemetry': {'raw_usage': {'promptTokenCount': 1000, 'candidatesTokenCount': 100}},
             'score': {'valid': False}}]
    row = benchmark.summarize(rows)['gemini-lite']
    assert (row['reliability_pct'], row['type_correct_pct']) == (50.0, 50.0)
    assert row['cost_per_1k_summaries_usd_regular'] == pytest.approx((1000 * 0.30 + 100 * 2.50) / 1e6 * 1000, abs=1e-4)
    assert row['provider'] == 'google_ai_studio'
