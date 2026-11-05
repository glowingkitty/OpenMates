#!/usr/bin/env python3
"""Actual public Python privacy facade over fresh PyO3 artifacts."""

# contract-test: supporting surface=sdks.pip assertions=pii.surface.semantic-parity
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
from openmates import SessionClientError, prepare_privacy, restore_privacy  # noqa: E402 - import follows sys.path setup for sibling runner modules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    capability = "local.privacy.v1"
    assert args.capability == capability
    raw = Path(args.fixture).read_bytes()
    vectors = json.loads(raw)["capabilities"][capability]["vectors"]
    assert vectors
    results = []
    for vector in vectors:
        before = copy.deepcopy(vector)
        value = copy.deepcopy(vector["input"])
        expand = vector.get("expand", {})
        if "text_bytes" in expand:
            value["text"] = "x" * expand["text_bytes"]
        if "mapping_count" in expand:
            value["mappings"] = [None] * expand["mapping_count"]
        if "encoded_bytes" in expand:
            value["mappings"] = [""]
            overhead = len(
                json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            value["mappings"] = ["x" * (expand["encoded_bytes"] - overhead)]
        if "existing_count" in expand:
            value["existing_mappings"] = [
                {"original": f"unrelated-{i}", "placeholder": f"[KEEP_{i}]"}
                for i in range(expand["existing_count"])
            ]
        if "email_repeats" in expand:
            value["text"] = "a@b.co " * expand["email_repeats"]
        if "prepare_json_bytes" in expand:
            value["existing_mappings"] = [
                {"original": "unrelated", "placeholder": "[KEEP]", "padding": ""}
            ]
            overhead = len(
                json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            value["existing_mappings"][0]["padding"] = "x" * (
                expand["prepare_json_bytes"] - overhead
            )
        if "canonical_json_bytes" in expand:
            value["mappings"][1] = "x" * (
                expand["canonical_json_bytes"] - expand["canonical_overhead"]
            )
        if "placeholder_bytes" in expand:
            value["text"] = "x" * expand["plain_repeats"]
            value["existing_mappings"] = [
                {
                    "original": "x",
                    "placeholder": "[" + "A" * (expand["placeholder_bytes"] - 2) + "]",
                }
            ]
        if "original_bytes" in expand:
            value["text"] = "[X]" * expand["token_repeats"]
            value["mappings"] = [
                {"original": "y" * expand["original_bytes"], "placeholder": "[X]"}
            ]
        try:
            if value["operation"] == "prepare":
                output = prepare_privacy(
                    value["text"],
                    memories=value["memories"],
                    existing_mappings=value["existing_mappings"],
                    enhanced=value["enhanced"],
                )
            else:
                output = {"text": restore_privacy(value["text"], value["mappings"])}
        except SessionClientError as error:
            assert error.code == vector.get("error"), vector["id"]
            assert "synthetic private value" not in str(error)
        else:
            assert "error" not in vector, vector["id"]
            if "expected_text_length" in vector:
                assert (
                    output["text"]
                    == vector.get("expected_repeat_character", "x")
                    * vector["expected_text_length"]
                )
            if "expected" in vector:
                assert output == vector["expected"], vector["id"]
            if "mapping_values" in vector:
                assert [
                    {"original": m["original"], "type": m["type"]}
                    for m in output["mappings"]
                ] == vector["mapping_values"], vector["id"]
                tokens = [m["placeholder"] for m in output["mappings"]]
                assert len(set(tokens)) == len(tokens)
                assert all(re.fullmatch(r"\[OM_PII_[A-F0-9]{32}\]", t) for t in tokens)
                for mapping in output["mappings"]:
                    assert mapping["placeholder"] in output["text"]
                    assert mapping["original"] not in output["text"]
            if "prepared_text_length" in vector:
                assert (
                    len(output["text"].encode("utf-8"))
                    == vector["prepared_text_length"]
                )
            if vector.get("prepared_token_output"):
                assert output["text"] == output["mappings"][0]["placeholder"]
            if vector.get("roundtrip_input"):
                assert (
                    restore_privacy(output["text"], output["mappings"]) == value["text"]
                )
            if "restored" in vector:
                assert (
                    restore_privacy(output["text"], output["mappings"])
                    == vector["restored"]
                ), vector["id"]
        assert vector == before, "caller fixture must remain unchanged"
        results.append({"id": vector["id"], "status": "passed"})
    print(
        json.dumps(
            {
                "capability": capability,
                "language": "python",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
