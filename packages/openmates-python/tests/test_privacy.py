"""Public privacy facade validation and real native library contracts."""
# contract-test: supporting surface=sdks.pip assertions=pii.surface.semantic-parity
import copy
import pytest
from openmates import SessionClientError, prepare_privacy, restore_privacy


# contract-test: supporting surface=sdks.pip assertions=pii.surface.semantic-parity
@pytest.mark.parametrize("value", [float("nan"),float("inf"),object(),{1:"synthetic-secret"},"\ud800",9007199254740992])
def test_reject_lossy_values_before_native_dispatch(value):
    with pytest.raises(SessionClientError) as caught:
        prepare_privacy("plain",memories=[value])
    assert caught.value.code == "invalid_argument"
    assert "synthetic-secret" not in str(caught.value)


# contract-test: supporting surface=sdks.pip assertions=pii.surface.semantic-parity
def test_local_boundaries_and_strict_keywords():
    for operation in [lambda:restore_privacy("x"*1048577,[]),lambda:restore_privacy("x",[None]*1025),lambda:prepare_privacy("x",memories=[None]*1024,existing_mappings=[None]),lambda:prepare_privacy("x",enhanced=1)]:
        with pytest.raises(SessionClientError) as caught:
            operation()
        assert caught.value.code == "invalid_argument"
    with pytest.raises(TypeError):
        prepare_privacy("plain",unknown="synthetic-secret")
    cycle=[]
    cycle.append(cycle)
    with pytest.raises(SessionClientError):
        prepare_privacy("plain",memories=cycle)


# contract-test: supporting surface=sdks.pip assertions=pii.surface.semantic-parity
def test_native_mapping_metadata_and_caller_inputs():
    mappings=[{"original":"fictional@example.invalid","placeholder":"[KNOWN_EMAIL]","opaque":{"retained":True}}]
    before=copy.deepcopy(mappings)
    prepared=prepare_privacy("fictional@example.invalid",existing_mappings=mappings)
    assert prepared == {"text":"[KNOWN_EMAIL]","mappings":[{**mappings[0],"type":"OTHER"}]}
    assert restore_privacy(prepared["text"],prepared["mappings"]) == "fictional@example.invalid"
    assert mappings == before
    with pytest.raises(SessionClientError) as caught:
        prepare_privacy("synthetic-secret",enhanced=True)
    assert caught.value.code == "invalid_argument"
    assert "synthetic-secret" not in str(caught.value)
