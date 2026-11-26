"""Pure admission tests for the private pre-deploy DevTest lane."""

# contract-test-file: tooling

import hashlib
import json
import os
import subprocess

import pytest

from scripts.ci_personal_devtest import admit, git, reconstruct


def inputs_and_env(surface="terminal"):
    pin = {
        "actor": "reviewed-operator",
        "surface": surface,
        "base": "a" * 40,
        "source": "b" * 40,
        "tree": "c" * 40,
        "recipient_sha256": "d" * 64,
    }
    env = {
        "GITHUB_REPOSITORY": "glowingkitty/OpenMates",
        "GITHUB_REF": "refs/heads/dev",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_SHA": "e" * 40,
        "GITHUB_ACTOR": pin["actor"],
        "GITHUB_TRIGGERING_ACTOR": pin["actor"],
        "DEVTEST_SURFACE": pin["surface"],
        "DEVTEST_BASE": pin["base"],
        "DEVTEST_SOURCE": pin["source"],
        "DEVTEST_TREE": pin["tree"],
        "DEVTEST_OWNER": "d13d",
        "DEVTEST_PATCH_SHA256": "f" * 64,
        "DEVTEST_REVIEW": json.dumps(pin),
    }
    return {"candidate_patch_url": "https://nbg1.your-objectstorage.com/private.patch?signature=fixture"}, env


def test_admit_binds_exact_protected_candidate_and_harness():
    inputs, env = inputs_and_env()
    result = admit(env, inputs, "d" * 64)
    assert result["source"] == "b" * 40
    assert result["harness"] == "e" * 40
    assert result["base"] == "a" * 40
    assert result["tree"] == "c" * 40
    assert result["recipient_sha256"] == "d" * 64
    assert "candidate_patch_url" not in result


@pytest.mark.parametrize(("key", "bad_value"), [
    ("GITHUB_REPOSITORY", "another/OpenMates"),
    ("GITHUB_REF", "refs/heads/fork"),
    ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_TRIGGERING_ACTOR", "unreviewed-operator"),
    ("DEVTEST_REVIEW", ""),
    ("DEVTEST_SOURCE", "a" * 40),
    ("DEVTEST_BASE", "b" * 40),
    ("DEVTEST_TREE", "e" * 40),
    ("DEVTEST_SURFACE", "web"),
])
def test_rejects_unreviewed_or_foreign_private_candidate(key, bad_value):
    inputs, env = inputs_and_env()
    env[key] = bad_value
    with pytest.raises(ValueError):
        admit(env, inputs, "d" * 64)


def test_rejects_wrong_recipient_or_non_artifact_host():
    inputs, env = inputs_and_env()
    with pytest.raises(ValueError):
        admit(env, inputs, "0" * 64)
    inputs["candidate_patch_url"] = "https://outside.invalid/patch?signature=fixture"
    with pytest.raises(ValueError):
        admit(env, inputs, "d" * 64)


def test_baseline_ignores_untrusted_checkout_and_uses_workflow_sha():
    _, env = inputs_and_env()
    for key in ("DEVTEST_TREE", "DEVTEST_OWNER", "DEVTEST_PATCH_SHA256", "DEVTEST_REVIEW"):
        del env[key]
    result = admit(env, {}, "d" * 64)
    assert not result["candidate"]
    assert result["source"] == result["harness"] == env["GITHUB_SHA"]


def test_a_patch_url_alone_cannot_fall_back_to_the_baseline():
    inputs, env = inputs_and_env()
    del env["DEVTEST_TREE"]
    with pytest.raises(ValueError):
        admit(env, inputs, "d" * 64)

def test_web_baseline_can_use_the_same_local_origin_as_a_candidate():
    _, env = inputs_and_env("web")
    for key in ("DEVTEST_TREE", "DEVTEST_OWNER", "DEVTEST_PATCH_SHA256", "DEVTEST_REVIEW"):
        del env[key]
    env["DEVTEST_LOCAL_BUILD"] = "true"
    assert admit(env, {}, "d" * 64)["local_web"]


def test_reconstructs_exact_detached_candidate_from_a_clean_base(tmp_path):
    subject = tmp_path / "subject"
    subject.mkdir()
    subprocess.run(["git", "init", "-q", str(subject)], check=True)
    status = subject / "fixture.txt"
    status.write_text("trusted base\n")
    git(subject, "add", str(status))
    original_tree = git(subject, "write-tree")
    author = {
        **os.environ,
        "GIT_AUTHOR_NAME": "OpenMates CI", "GIT_AUTHOR_EMAIL": "ci@example.com",
        "GIT_COMMITTER_NAME": "OpenMates CI", "GIT_COMMITTER_EMAIL": "ci@example.com",
        "GIT_AUTHOR_DATE": "2026-10-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-01T00:00:00+00:00",
    }
    base = git(subject, "commit-tree", original_tree, "-m", "Synthetic base", env=author)
    git(subject, "checkout", "--detach", base)
    status.write_text("reviewed candidate\n")
    patch = subprocess.check_output(["git", "-C", str(subject), "diff", "--binary"])
    git(subject, "add", str(status))
    tree = git(subject, "write-tree")
    source = git(subject, "commit-tree", tree, "-p", base, "-m", "CI candidate for session d13d", env=author)
    git(subject, "reset", "--hard", base)
    identity = {"base": base, "tree": tree, "source": source, "owner": "d13d",
                "patch_sha256": hashlib.sha256(patch).hexdigest()}

    with pytest.raises(ValueError, match="patch digest"):
        reconstruct(subject, identity, patch + b"tampered")
    reconstruct(subject, identity, patch)
    assert git(subject, "rev-parse", "HEAD") == source
    assert status.read_text() == "reviewed candidate\n"
    assert subprocess.run(["git", "-C", str(subject), "symbolic-ref", "-q", "HEAD"]).returncode == 1
