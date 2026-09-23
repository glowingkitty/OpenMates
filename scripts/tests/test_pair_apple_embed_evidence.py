"""The pairing gate must expose absent native screenshots by exact embed key."""

from pathlib import Path

from scripts import pair_apple_embed_evidence


# contract-test: tooling
def test_pair_embed_evidence_requires_each_native_preview_and_fullscreen(tmp_path: Path) -> None:
    web_contracts = []
    native_attachments = []
    for dimension in sorted(pair_apple_embed_evidence.REQUIRED_EMBED_REGISTRY_DIMENSIONS):
        entries = []
        for surface in ("preview", "fullscreen"):
            filename = f"{dimension}/example-{surface}.png"
            screenshot = tmp_path / filename
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            screenshot.write_bytes(b"png")
            entries.append({"registryKey": "example", "surface": surface, "screenshotPath": filename})
            native_file = f"{dimension}-{surface}.png"
            (tmp_path / native_file).write_bytes(b"png")
            native_attachments.append({
                "suggestedHumanReadableName": f"Embed parity|example|{surface}|{dimension}_0_UUID.png",
                "exportedFileName": native_file,
            })
        web_contracts.append((tmp_path / f"embeds.{dimension}.json", {
            "dimension": {"id": dimension},
            "registrySurfaces": entries,
        }))

    native_export = [(tmp_path / "manifest.json", [{"attachments": native_attachments}])]
    report, errors = pair_apple_embed_evidence.pair_evidence(web_contracts, native_export)
    assert errors == []
    assert len(report["pairs"]) == 2 * len(pair_apple_embed_evidence.REQUIRED_EMBED_REGISTRY_DIMENSIONS)
    assert all(pair["reviewStatus"] == "unreviewed" for pair in report["pairs"])

    native_attachments.pop()
    report, errors = pair_apple_embed_evidence.pair_evidence(web_contracts, native_export)
    assert len(report["pairs"]) == 2 * len(pair_apple_embed_evidence.REQUIRED_EMBED_REGISTRY_DIMENSIONS) - 1
    assert "missing 1 native screenshots" in errors
