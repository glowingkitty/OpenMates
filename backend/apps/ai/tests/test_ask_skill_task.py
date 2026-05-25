"""
Regression tests for AI ask task chat-history boundaries.

Compression summaries are server-readable context for model processing. They
must stay out of Directus chat history unless a client supplies client-encrypted
ciphertext for that history entry.
"""

from pathlib import Path


def test_chat_compression_does_not_persist_server_encrypted_summary_to_history():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    compression_block = source.split("Compression succeeded:", maxsplit=1)[1]
    compression_block = compression_block.split(
        "# Update request_data.message_history with compressed version",
        maxsplit=1,
    )[0]

    assert "persist_new_chat_message" not in compression_block
