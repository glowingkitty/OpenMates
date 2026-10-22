"""Provider-free prompt experiment isolation checks."""
# contract-test-file: infrastructure
import copy

import pytest

from backend.scripts import benchmark_daily_inspiration_prompt as experiment


def test_experiment_restores_writer_arms_and_production_entrypoints():
    base = experiment.base
    original = {name: getattr(base, name) for name in (
        'ARMS', 'ARM_MODELS', 'ARM_PROFILES', 'qualify_batch', 'build_manifest', 'TOPICS')}
    with pytest.raises(RuntimeError, match='stop'):
        with experiment.configured_benchmark():
            assert len(base.ARMS) == 3
            assert base.ARM_MODELS['mercury3_clear'] == 'inception/mercury-3'
            assert base.DISCOVERY_BATCH_SIZE == 1
            assert base.TOPICS['en'].split('|')[0] == 'Aurora borealis'
            raise RuntimeError('stop')
    assert all(getattr(base, name) is value for name, value in original.items())


@pytest.mark.parametrize('arm', ['gemini38_only', 'mercury3_only'])
def test_control_request_is_identical_object_not_reformatted(arm):
    request = {'message_history': [{'role': 'user', 'content': 'original evidence'}]}
    assert experiment.transform_request(request, [], 'video', 'de', arm) is request


def test_optimized_arm_changes_prompt_not_mercury_model_sampling_or_source_identity(monkeypatch):
    from backend.apps.ai.daily_inspiration import writer_prompt
    seen = []
    def prepare(*args):
        seen.append(args)
        return {'message_history': [{'role': 'user', 'content': 'clear packet'}],
                'tool_definition': {'name': 'same schema'}}
    monkeypatch.setattr(writer_prompt, 'build_writer_request', prepare)
    original = {'model_id': 'inception/mercury-3', 'temperature': 1.0,
                'max_output_tokens': 4096, 'tool_definition': {'original': True},
                'message_history': [], 'fallback_models': [], 'allow_retries': False}
    before = copy.deepcopy(original)
    source = {'approved': {'wiki_title': 'Exact title', 'extract': 'Exact public evidence'}}
    actual = experiment.transform_request(original, [source], 'wiki', 'de', 'mercury3_clear')
    assert original == before
    assert actual['model_id'] == 'inception/mercury-3'
    assert actual['reasoning_effort'] == 'low' and actual['temperature'] == .5
    assert actual['max_output_tokens'] == 4096
    assert actual['fallback_models'] == [] and actual['allow_retries'] is False
    assert seen == [('wiki', 'de', [source['approved']], original['tool_definition'])]
