"""Keep Vault-encrypted embed data out of durable writes."""

from pathlib import Path


# contract-test: tooling
def test_encrypting_for_client_delivery_and_durable_writes_have_separate_boundaries(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    import code_quality_guard

    path = "backend/core/api/app/services/embed_service.py"
    source = """
def flatten():
    return {}

class EmbedService:
    async def update_embed_with_results(self, client, embed_id, data):
        lock_key = f"lock:embed:{embed_id}"
        await client.set(lock_key, "lease", nx=True)
        encrypted_content = await self.encryption_service.encrypt_with_user_key(data)
        await self.send_embed_data_to_client(data, cache={"encrypted_content": encrypted_content})

    async def persist_client_ciphertext(self, encrypted_content):
        await self.directus.update_embed({"encrypted_content": encrypted_content})
"""
    monkeypatch.setattr(code_quality_guard, "_staged_file_text", lambda _: source)
    assert code_quality_guard._audit_backend_embed_vault_boundaries([path]) == []

    source += """
    async def persist_vault_ciphertext(self, data):
        encrypted_content = await self.encryption_service.encrypt_with_user_key(data)
        await self.directus.update_embed({"encrypted_content": encrypted_content})
"""
    issues = code_quality_guard._audit_backend_embed_vault_boundaries([path])
    assert len(issues) == 1
    assert "persist_vault_ciphertext writes Vault-encrypted data" in issues[0]
