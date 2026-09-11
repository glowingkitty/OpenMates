"""Bounded diagnostic text with complete local evidence retained on overflow."""
import hashlib
from pathlib import Path


def diagnostic(text: str, directory: Path, *, budget: int = 4000) -> str:
    if len(text) <= budget:
        return text
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (hashlib.sha256(text.encode()).hexdigest()[:20] + '.log')
    path.write_text(text)
    path.chmod(0o600)
    first = budget // 4
    return (text[:first] + f'\n… {len(text) - budget} characters retained in {path}\n'
            + text[-(budget - first):])
