# contract-test-file: infrastructure
"""Domain-policy image audits follow the actual backend-qualified image layout."""
from pathlib import Path

from scripts import audit_domain_security as audit


def test_supported_api_worker_selfhost_images_ship_loadable_domain_policy():
    assert audit._audit_image_copy_contracts() == []
    assert audit.audit_domain_security(verify_images=True) == []
    source = audit.DEFAULT_CONFIG_DIR
    assert (source / "domain_security.py").is_file()
    for name in ("allowed", "restricted", "patterns"):
        assert (source / f"domain_security_{name}.encrypted").is_file()


def test_worker_without_policy_tree_still_blocks_publication(monkeypatch, tmp_path):
    root = audit.REPO_ROOT
    for name in ("Dockerfile", "Dockerfile.selfhost", "Dockerfile.celery"):
        relative = Path("backend/core/api") / name
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (root / relative).read_text()
        if name == "Dockerfile.celery":
            content = content.replace("COPY backend /app/backend", "COPY scripts /app/scripts")
            content += '\n# COPY backend /app/backend\nRUN echo "COPY backend /app/backend"\nCOPY backend_assets /app/backend\n'
        target.write_text(content)
    for name in ("sign-domain-security-policy.yml", "publish-selfhost-images.yml"):
        relative = Path(".github/workflows") / name
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((root / relative).read_text())
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    assert audit._audit_image_copy_contracts() == [
        "backend/core/api/Dockerfile.celery does not include the domain-policy source tree"
    ]
