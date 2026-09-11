# contract-test-file: tooling
"""Verify archive fixture encryption without running an OpenMates application.

Only the candidate's pure client crypto functions execute on synthetic data.
No browser, Docker service, provider, account or HTTP request is used locally.
The complete sharing/viewer flow remains a GitHub-only original-spec gate.
See docs/architecture/isolated-github-tests.md.
"""
import subprocess
from pathlib import Path


def test_archive_fixture_keeps_content_encrypted_and_chat_wrappers_decrypt():
    root = Path(__file__).resolve().parents[2]
    program = """
import {pathToFileURL} from 'node:url';
import {randomBytes} from 'node:crypto';
import assert from 'node:assert/strict';
globalThis.fetch = () => {throw new Error('Pure fixture test must not request network');};
const root = process.argv[1];
const {buildFixture,TRANSCRIPT} = await import(pathToFileURL(root+'/scripts/ci_shared_chat_fixture.mjs'));
const crypto = await import(pathToFileURL(root+'/frontend/packages/openmates-cli/src/crypto.ts'));
const master = randomBytes(32);
const fixture = await buildFixture(root,'synthetic-owner',master);
assert(!JSON.stringify(fixture).includes(TRANSCRIPT));
const key = await crypto.decryptBytesWithAesGcm(fixture.chat.encrypted_chat_key,master);
const reference = await crypto.decryptWithAesGcmCombined(fixture.message.encrypted_content,key);
assert(reference.includes(fixture.embed.embed_id));
const wrapper = fixture.keys.find(k=>k.key_type==='chat');
assert.equal(wrapper.hashed_chat_id,fixture.embed.hashed_chat_id);
const embedKey = await crypto.decryptBytesWithAesGcm(wrapper.encrypted_embed_key,key);
const content = JSON.parse(await crypto.decryptWithAesGcmCombined(fixture.embed.encrypted_content,embedKey));
assert.equal(content.transcript,TRANSCRIPT);
assert.equal(content.app_id,'audio');
assert.equal(content.skill_id,'transcribe');
assert.equal(content.status,'finished');
const other = await buildFixture(root,'synthetic-other',randomBytes(32));
assert.notEqual(other.chat.id,fixture.chat.id);
assert.notEqual(other.embed.hashed_user_id,fixture.embed.hashed_user_id);
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", program, str(root)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
