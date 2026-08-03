#!/usr/bin/env python3
"""Audit security randomness patterns that repeatedly regress across clients.

The audit is static, fast, and emits only repository paths and rule codes. It
keeps human-code policy separate from later media nonce and Apple fail-closed
checks so focused tests can identify the owning implementation slice.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

HUMAN_CODE_RULES = {
    "backend/core/api/app/tasks/email_tasks/verification_email_task.py": ("random.choices", "generate_digit_code"),
    "backend/core/api/app/tasks/email_tasks/action_verification_email_task.py": ("random.choices", "generate_digit_code"),
    "backend/core/api/app/tasks/email_tasks/email_change_verification_task.py": ("random.choices", "generate_digit_code"),
    "backend/core/api/app/tasks/email_tasks/recovery_account_email_task.py": ("random.choices", "generate_digit_code"),
    "backend/core/api/app/routes/auth_routes/auth_2fa_utils.py": ("string.ascii_uppercase + string.digits", "HUMAN_CODE_ALPHABET"),
    "backend/core/api/app/services/referral_service.py": ("string.ascii_uppercase + string.digits", "HUMAN_CODE_ALPHABET"),
    "backend/core/api/app/services/directus/user/user_creation.py": ("random.choices", "generate_random_string"),
    "backend/core/directus/setup/setup_schemas.py": ("random.choices", "secrets.choice"),
    "backend/core/api/app/routes/payments.py": ("random.choices", "secrets.choice"),
    "backend/core/api/app/routes/admin.py": ("random.choices", "secrets.choice"),
    "frontend/packages/ui/src/services/shortUrlEncryption.ts": ("values[i] % BASE62_CHARS.length", "SHORT_KEY_LENGTH = 22"),
    "frontend/packages/openmates-cli/src/crypto.ts": ("randomByte %", "API_KEY_CHARS"),
    "frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte": ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", "maxUnbiasedValue"),
    "apple/OpenMates/Sources/Features/Settings/Views/SettingsDeveloperFull.swift": ("% alphabet.count", "SecureRandom"),
    "apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift": ("base64URLEncodedString()", "secureRecoveryKey"),
    "apple/OpenMates/Sources/Features/Auth/ViewModels/PairLoginRuntime.swift": ("% alphabet.count", "SecureRandom"),
}

REJECTION_SAMPLING_RULES = {
    "frontend/packages/ui/src/services/shortUrlEncryption.ts": (
        "maxUnbiasedValue",
        "value >= maxUnbiasedValue",
    ),
    "frontend/packages/ui/src/services/cryptoService.ts": (
        "maxUnbiasedValue",
        "value < maxUnbiasedValue",
    ),
    "frontend/packages/openmates-cli/src/crypto.ts": (
        "maxUnbiasedValue",
        "value < maxUnbiasedValue",
    ),
    "frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte": (
        "maxUnbiasedValue",
        "value >= maxUnbiasedValue",
    ),
    "apple/OpenMates/Sources/Core/Crypto/CryptoManager.swift": (
        "maxUnbiasedValue",
        "value < maxUnbiasedValue",
    ),
}


def audit_human_code_randomness(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for relative_path, (forbidden, required) in HUMAN_CODE_RULES.items():
        source = (root / relative_path).read_text(encoding="utf-8")
        if forbidden in source:
            findings.append(f"{relative_path}:forbidden_randomness")
        if required not in source:
            findings.append(f"{relative_path}:required_guard_missing")
    for relative_path, required_markers in REJECTION_SAMPLING_RULES.items():
        source = (root / relative_path).read_text(encoding="utf-8")
        if any(marker not in source for marker in required_markers):
            findings.append(f"{relative_path}:rejection_sampling_guard_missing")
    return findings


def main() -> int:
    findings = audit_human_code_randomness()
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
