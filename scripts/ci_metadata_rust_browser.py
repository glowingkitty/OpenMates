"""Exact default-off metadata singleton. No generic SDK/module permission."""

from __future__ import annotations
import hashlib
import json
import os
import re
import stat

FEATURE = "browser-metadata-prototype"
SPEC = "rust-core-native-metadata-prototype.spec.ts"
STARTUP_SPEC = "rust-core-initial-startup.spec.ts"
PAIRED_SPEC = "web-essential-startup-performance.spec.ts"
FIRST_SESSION_SPEC = "rust-core-first-session.spec.ts"
NATIVE_RECOVERY_SPEC = "rust-core-native-recovery-port.spec.ts"
ACTIVECHAT_SPEC = "rust-core-activechat-send.spec.ts"
NEW_CHAT_SPEC = "rust-core-new-chat-send.spec.ts"
NEW_CHAT_INPUTS = frozenset(
    (
        "frontend/apps/web_app/scripts/rust-metadata-module-closure.mjs",
        "frontend/apps/web_app/scripts/rust-recovery-module-closure.mjs",
        "frontend/apps/web_app/scripts/vite-plugin-rust-core.mjs",
        "frontend/apps/web_app/src/lib/rustCore/RustStartupChat.svelte",
        "frontend/apps/web_app/src/lib/rustCore/production.worker.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionAssets.d.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionBootstrap.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionLoader.ts",
        "frontend/apps/web_app/src/routes/+page.svelte",
        "frontend/apps/web_app/tests/helpers/chat-test-helpers.ts",
        "frontend/apps/web_app/tests/helpers/cookie-audit.ts",
        "frontend/apps/web_app/tests/helpers/isolated-essential-startup-profile.ts",
        "frontend/apps/web_app/tests/helpers/native-pair-login-flow.ts",
        "frontend/apps/web_app/tests/helpers/rust-owned-send-terminal-gate.ts",
        "frontend/apps/web_app/tests/rust-core-new-chat-send.spec.ts",
        "frontend/apps/web_app/tests/signup-flow-helpers.ts",
        "frontend/packages/ui/src/components/ChatMessageNoTipTap.svelte",
        "frontend/packages/ui/src/components/RustSavedChatComposer.svelte",
        "frontend/packages/ui/src/components/RustSavedChatView.svelte",
        "frontend/packages/ui/src/components/embeds/MarkdownContent.svelte",
        "frontend/packages/ui/src/services/rustCore/browserAdapters.ts",
        "frontend/packages/ui/src/services/rustCore/initialSyncOperation.ts",
        "frontend/packages/ui/src/services/rustCore/newChatNativeRouting.ts",
        "frontend/packages/ui/src/services/rustCore/originalSavedChatSender.ts",
        "frontend/packages/ui/src/services/rustCore/productionInitialSyncSession.ts",
        "frontend/packages/ui/src/services/rustCore/productionLegacyProducerRetirement.ts",
        "frontend/packages/ui/src/services/rustCore/productionOwnedReadView.ts",
        "frontend/packages/ui/src/services/rustCore/productionSavedChatPlatform.ts",
        "frontend/packages/ui/src/services/rustCore/productionSavedChatSession.ts",
        "frontend/packages/ui/src/services/rustCore/protocol.ts",
        "frontend/packages/ui/src/services/rustCore/savedChatSendController.ts",
        "frontend/packages/ui/src/services/rustCore/sendOperation.ts",
        "frontend/packages/ui/src/services/rustCore/sendProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/workerHost.ts",
        "frontend/packages/ui/src/services/rustCore/workerRuntime.ts",
        "scripts/ci_chat_metadata_recovery.mjs",
    )
)
ACTIVECHAT_INPUTS = frozenset(
    (
        "frontend/apps/web_app/scripts/rust-metadata-module-closure.mjs",
        "frontend/apps/web_app/scripts/rust-recovery-module-closure.mjs",
        "frontend/apps/web_app/scripts/vite-plugin-rust-core.mjs",
        "frontend/apps/web_app/src/lib/rustCore/RustStartupChat.svelte",
        "frontend/apps/web_app/src/lib/rustCore/production.worker.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionAssets.d.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionBootstrap.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionLoader.ts",
        "frontend/apps/web_app/src/routes/+page.svelte",
        "frontend/apps/web_app/tests/helpers/chat-test-helpers.ts",
        "frontend/apps/web_app/tests/helpers/cookie-audit.ts",
        "frontend/apps/web_app/tests/helpers/isolated-essential-startup-profile.ts",
        "frontend/apps/web_app/tests/helpers/native-pair-login-flow.ts",
        "frontend/apps/web_app/tests/helpers/rust-owned-send-terminal-gate.ts",
        "frontend/apps/web_app/tests/rust-core-activechat-send.spec.ts",
        "frontend/apps/web_app/tests/signup-flow-helpers.ts",
        "frontend/packages/ui/src/components/ChatMessageNoTipTap.svelte",
        "frontend/packages/ui/src/components/RustSavedChatComposer.svelte",
        "frontend/packages/ui/src/components/RustSavedChatView.svelte",
        "frontend/packages/ui/src/components/embeds/MarkdownContent.svelte",
        "frontend/packages/ui/src/services/rustCore/browserAdapters.ts",
        "frontend/packages/ui/src/services/rustCore/initialSyncOperation.ts",
        "frontend/packages/ui/src/services/rustCore/originalSavedChatSender.ts",
        "frontend/packages/ui/src/services/rustCore/productionInitialSyncSession.ts",
        "frontend/packages/ui/src/services/rustCore/productionLegacyProducerRetirement.ts",
        "frontend/packages/ui/src/services/rustCore/productionOwnedReadView.ts",
        "frontend/packages/ui/src/services/rustCore/productionSavedChatPlatform.ts",
        "frontend/packages/ui/src/services/rustCore/productionSavedChatSession.ts",
        "frontend/packages/ui/src/services/rustCore/protocol.ts",
        "frontend/packages/ui/src/services/rustCore/savedChatSendController.ts",
        "frontend/packages/ui/src/services/rustCore/sendOperation.ts",
        "frontend/packages/ui/src/services/rustCore/sendProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/workerHost.ts",
        "frontend/packages/ui/src/services/rustCore/workerRuntime.ts",
        "scripts/ci_chat_metadata_recovery.mjs",
    )
)
NATIVE_RECOVERY_INPUTS = frozenset(
    (
        "frontend/apps/web_app/scripts/rust-metadata-module-closure.mjs",
        "frontend/apps/web_app/scripts/rust-recovery-module-closure.mjs",
        "frontend/apps/web_app/scripts/vite-plugin-rust-core.mjs",
        "frontend/apps/web_app/src/lib/rustCore/production.worker.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionBootstrap.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionLoader.ts",
        "frontend/apps/web_app/src/routes/dev/preview/[...path]/+page.svelte",
        "frontend/apps/web_app/tests/helpers/chat-hydration.ts",
        "frontend/apps/web_app/tests/helpers/chat-test-helpers.ts",
        "frontend/apps/web_app/tests/helpers/cookie-audit.ts",
        "frontend/apps/web_app/tests/helpers/native-pair-login-flow.ts",
        "frontend/apps/web_app/tests/helpers/rust-physical-recovery-browser.ts",
        "frontend/apps/web_app/tests/helpers/rust-recovery-finalizer-scheduler.ts",
        "frontend/apps/web_app/tests/rust-core-native-recovery-port.spec.ts",
        "frontend/packages/ui/src/components/debug/RustCoreSessionHarness.preview.ts",
        "frontend/packages/ui/src/components/debug/RustCoreSessionHarness.svelte",
        "frontend/packages/ui/src/services/rustCore/browserAdapters.ts",
        "frontend/packages/ui/src/services/rustCore/browserCacheProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/browserCredentialStorage.ts",
        "frontend/packages/ui/src/services/rustCore/browserRecoveryTransport.ts",
        "frontend/packages/ui/src/services/rustCore/credentialCasProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/initialSyncOperation.ts",
        "frontend/packages/ui/src/services/rustCore/initialSyncProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/mainMetadataStoreOperation.ts",
        "frontend/packages/ui/src/services/rustCore/ownedLocalReadProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/phasedCacheMonitorOperation.ts",
        "frontend/packages/ui/src/services/rustCore/protocol.ts",
        "frontend/packages/ui/src/services/rustCore/recoveredReplyStoreOperation.ts",
        "frontend/packages/ui/src/services/rustCore/recoveryFinalizationOperation.ts",
        "frontend/packages/ui/src/services/rustCore/savedReadProtocol.ts",
        "frontend/packages/ui/src/services/rustCore/sendOperation.ts",
        "frontend/packages/ui/src/services/rustCore/workerCredentials.ts",
        "frontend/packages/ui/src/services/rustCore/workerHost.ts",
        "frontend/packages/ui/src/services/rustCore/workerRuntime.ts",
        "scripts/ci_chat_metadata_recovery.mjs",
    )
)
# Finite web/provider source closure, used ONLY by the new singleton.
FIRST_SESSION_INPUTS = frozenset(
    (
        "frontend/apps/web_app/scripts/vite-plugin-rust-core.mjs",
        "frontend/apps/web_app/src/lib/rustCore/firstSessionProvider.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionAssets.d.ts",
        "frontend/apps/web_app/src/lib/rustCore/productionLoader.ts",
        "frontend/apps/web_app/src/routes/+page.svelte",
        "frontend/apps/web_app/tests/rust-core-first-session.spec.ts",
        "frontend/packages/ui/src/services/cryptoKeyStorage.ts",
        "frontend/packages/ui/src/services/rustCore/firstSessionNegativeLifetime.ts",
        "frontend/packages/ui/src/services/rustCore/firstSessionPlatform.ts",
        "frontend/packages/ui/src/services/rustCore/originalFirstSessionSource.ts",
        "frontend/packages/ui/src/services/rustCore/productionInitialSyncSession.ts",
        "frontend/packages/ui/src/services/rustCore/protocol.ts",
        "frontend/packages/ui/src/services/rustCore/workerHost.ts",
        "frontend/packages/ui/src/services/rustCore/workerRuntime.ts",
        "frontend/packages/ui/src/services/userDB.ts",
        "frontend/packages/ui/src/stores/authSessionActions.ts",
        "frontend/packages/ui/src/stores/userProfile.ts",
    )
)
WEB_INPUTS = (
    "frontend/packages/ui/src/config/api.ts",
    "frontend/packages/ui/src/config/apiEndpointPolicy.ts",
    "frontend/apps/web_app/src/lib/rustCore/metadataConfiguration.ts",
    "frontend/apps/web_app/src/lib/rustCore/metadata.worker.ts",
    "frontend/apps/web_app/src/lib/rustCore/metadataPrototype.ts",
    "frontend/packages/ui/src/services/rustCore/metadataAuthLifetime.ts",
    "frontend/packages/ui/src/stores/authLoginLogoutActions.ts",
    "frontend/apps/web_app/src/lib/rustCore/metadataPrototypeCI.ts",
)
NATIVE_SOURCE = "packages/openmates-rust/src/platform/browser_metadata_native.js"
EXTRA_INPUTS = frozenset((*WEB_INPUTS, NATIVE_SOURCE))
CRYPTO_SOURCE = "packages/openmates-browser-bindings/src/browser_crypto.rs"
RECOVERY_SOURCE = "packages/openmates-rust/src/platform/browser_recovery_port.rs"
SOURCE_PINS = {
    "packages/openmates-rust/src/platform/browser_metadata_native.js": "7d6404a17e6b8e53057d9d876d6ef87d27b560fe98e5ec99e3c4524b55826735",
    "packages/openmates-rust/src/platform/browser_recovery_port.rs": "38bc86417aad3bf3115ba5f46655ddc9a5e98ab7d85f3a82718956b112c87386",
    "packages/openmates-browser-bindings/src/browser_crypto.rs": "735598f81f8e4272f432cb1cedcd64f5f63bb651599282d172d0a7dbebc6d928",
}
RECOVERY_MODULE_SHA256 = (
    "1bdc2c5ed63001a8ebc06a79d29a2df60ef357840f4d993a55f96de69a57903b"
)
CRYPTO_BYTES = b"\nexport function settlePrimitive(operation, settle) {\n  return operation.then(value => { settle(value, true); }, () => { settle(undefined, false); });\n}\n"
BASE_FILES = frozenset(
    {
        "openmates_browser.js",
        "openmates_browser_bg.wasm",
        "openmates_browser.d.ts",
        "openmates_browser_bg.wasm.d.ts",
    }
)
CRYPTO_PATH = r"snippets/openmates-browser-bindings-([a-f0-9]{16})/inline0\.js"
RECOVERY_PATH = r"snippets/openmates-sdk-([a-f0-9]{16})/inline0\.js"
NATIVE_PATH = (
    r"snippets/openmates-sdk-([a-f0-9]{16})/src/platform/browser_metadata_native\.js"
)


def targets(values):
    return type(values) is list and (
        values == [SPEC]
        or values == [STARTUP_SPEC]
        or values == [PAIRED_SPEC]
        or first_session_targets(values)
        or native_recovery_targets(values)
        or activechat_targets(values)
        or new_chat_targets(values)
    )


def first_session_targets(values):
    return type(values) is list and values == [FIRST_SESSION_SPEC]


def native_recovery_targets(values):
    return type(values) is list and values == [NATIVE_RECOVERY_SPEC]


def activechat_targets(values):
    return type(values) is list and values == [ACTIVECHAT_SPEC]


def new_chat_targets(values):
    return type(values) is list and values == [NEW_CHAT_SPEC]


def package_names(names):
    if not isinstance(names, (set, dict)) or not BASE_FILES - {
        "openmates_browser_bg.wasm.d.ts"
    } <= set(names):
        return False
    extras = set(names) - BASE_FILES
    if (
        len(extras) != 3
        or len(names) not in {6, 7}
        or any(type(name) is not str for name in names)
    ):
        return False
    crypto = [
        re.fullmatch(CRYPTO_PATH, name)
        for name in extras
        if re.fullmatch(CRYPTO_PATH, name)
    ]
    recovery = [
        re.fullmatch(RECOVERY_PATH, name)
        for name in extras
        if re.fullmatch(RECOVERY_PATH, name)
    ]
    native = [
        re.fullmatch(NATIVE_PATH, name)
        for name in extras
        if re.fullmatch(NATIVE_PATH, name)
    ]
    return (
        len(crypto) == len(recovery) == len(native) == 1
        and recovery[0][1] == native[0][1]
    )


def recovery_source_bound(inputs):
    # Original metadata source admission is held; only this exact successor
    # requires its reviewed Cargo partner. No generated-module grant is added.
    if (
        inputs.get("packages/openmates-rust/Cargo.toml")
        == "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6"
    ):
        return (
            inputs.get(RECOVERY_SOURCE)
            == "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478"
            and native_source_bound(inputs)
        )
    if inputs.get(RECOVERY_SOURCE) == SOURCE_PINS[RECOVERY_SOURCE]:
        return True
    return (
        inputs.get(RECOVERY_SOURCE)
        == "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478"
        and inputs.get("packages/openmates-rust/Cargo.toml")
        == "38a1e0eb7218dc52b3121d528b49411d481ef3a602e1e2d69e124520e3d3f441"
    )


def native_source_bound(inputs):
    bridge = "packages/openmates-rust/src/platform/browser_metadata_native.rs"
    bridge_hash = "fd9af1ccfc3c6fd1ebacf9e656140b821f5a5f5dd66a9a3eb97fdca007a91575"
    # Bind the known new kernel/bridge before old metadata/reply branches.
    if (
        inputs.get(NATIVE_SOURCE)
        == "2610b7f46fb61224dbaf405e3579a2b1ac95e90f7d28e9bfa095db6092289cf4"
        or inputs.get(bridge)
        == "ca2814f2f7c8f12b0bcdf4ad92b8afd3b1aa923f08f503086a2075a8beb06e3c"
    ):
        return (
            inputs.get(NATIVE_SOURCE)
            == "2610b7f46fb61224dbaf405e3579a2b1ac95e90f7d28e9bfa095db6092289cf4"
            and inputs.get(bridge)
            == "ca2814f2f7c8f12b0bcdf4ad92b8afd3b1aa923f08f503086a2075a8beb06e3c"
            and inputs.get(RECOVERY_SOURCE)
            == "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478"
            and inputs.get("packages/openmates-rust/Cargo.toml")
            in {
                "38a1e0eb7218dc52b3121d528b49411d481ef3a602e1e2d69e124520e3d3f441",
                "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6",
            }
        )
    if inputs.get(NATIVE_SOURCE) == SOURCE_PINS[NATIVE_SOURCE]:
        return (
            inputs.get(bridge) != bridge_hash
            and inputs.get("packages/openmates-rust/Cargo.toml")
            != "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6"
        )
    return (
        inputs.get(NATIVE_SOURCE)
        == "cf00e87ad951749f1c656af6f653dfac33f06c7d1b010883b60f19bf87ec044b"
        and inputs.get(bridge) == bridge_hash
        and inputs.get(RECOVERY_SOURCE)
        == "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478"
        and inputs.get("packages/openmates-rust/Cargo.toml")
        in {
            "38a1e0eb7218dc52b3121d528b49411d481ef3a602e1e2d69e124520e3d3f441",
            "6cdd02d6aeaf811428b8545d58e109d78f472585eba58067ae79b9e46f4511c6",
        }
    )


def package_modules(files, inputs, closed_dependencies):
    if (
        not package_names(files)
        or not isinstance(inputs, dict)
        or not recovery_source_bound(inputs)
        or not native_source_bound(inputs)
        or any(
            inputs.get(name) != value
            for name, value in SOURCE_PINS.items()
            if name not in {RECOVERY_SOURCE, NATIVE_SOURCE}
        )
    ):
        return False
    modules = set(files) - BASE_FILES
    for name in modules:
        raw = files[name]
        if type(raw) is not bytes:
            return False
        if re.fullmatch(CRYPTO_PATH, name) and raw != CRYPTO_BYTES:
            return False
        if (
            re.fullmatch(RECOVERY_PATH, name)
            and hashlib.sha256(raw).hexdigest() != RECOVERY_MODULE_SHA256
        ):
            return False
        if (
            re.fullmatch(NATIVE_PATH, name)
            and hashlib.sha256(raw).hexdigest() != inputs[NATIVE_SOURCE]
        ):
            return False
    javascript = files["openmates_browser.js"]
    if type(javascript) is not bytes:
        return False
    used = set()
    for name in sorted(modules):
        headers = [
            (
                index,
                (
                    "import * as import" + str(index) + ' from "./' + name + '"\n'
                ).encode(),
            )
            for index in (1, 2, 3)
        ]
        matches = [
            (index, header)
            for index, header in headers
            if javascript.count(header) == 1
        ]
        if len(matches) != 1 or matches[0][0] in used:
            return False
        index, header = matches[0]
        used.add(index)
        javascript = javascript.replace(header, b"", 1)
    return used == {1, 2, 3} and closed_dependencies(javascript)


def package_inventory(folder, inputs, sdk, closed_dependencies):
    """Finite physical tree, preserving ordinary package guard unchanged."""
    directories, identities, files = [], {}, {}

    def scan(path, depth=0):
        sdk.require(depth <= 4, "outputs")
        info = path.lstat()
        sdk.require(
            path.resolve() == path
            and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o022,
            "outputs",
        )
        directories.append((path, sdk.file_identity(info)))
        sdk.require(len(directories) <= 8, "outputs")
        entries = list(path.iterdir())
        sdk.require(len(entries) <= 8, "outputs")
        for entry in entries:
            info = entry.lstat()
            if stat.S_ISDIR(info.st_mode):
                scan(entry, depth + 1)
                continue
            name = entry.relative_to(folder).as_posix()
            sdk.require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and info.st_nlink == 1
                and not info.st_mode & 0o022
                and (
                    name in BASE_FILES
                    or any(
                        re.fullmatch(rule, name)
                        for rule in (CRYPTO_PATH, RECOVERY_PATH, NATIVE_PATH)
                    )
                ),
                "outputs",
            )
            raw = sdk.regular(entry, 64 * 1024**2)
            sdk.require(
                raw and sdk.file_identity(info) == sdk.file_identity(entry.lstat()),
                "outputs",
            )
            identities[entry] = sdk.file_identity(info)
            files[name] = raw
            sdk.require(len(files) <= 7, "outputs")

    scan(folder)
    sdk.require(package_modules(files, inputs, closed_dependencies), "outputs")
    expected_dirs = {folder}
    for name in files:
        parent = (folder / name).parent
        while parent != folder:
            expected_dirs.add(parent)
            parent = parent.parent
    sdk.require(set(path for path, _ in directories) == expected_dirs, "outputs")
    for path, identity in directories:
        sdk.require(sdk.file_identity(path.lstat()) == identity, "outputs")
    rows, total = [], 0
    for name, raw in sorted(files.items()):
        path = folder / name
        sdk.require(
            sdk.file_identity(path.lstat()) == identities[path]
            and sdk.sha(sdk.regular(path)) == sdk.sha(raw),
            "outputs",
        )
        if name.endswith(".wasm"):
            sdk.require(raw[:8] == b"\0asm\x01\0\0\0", "outputs")
        else:
            raw.decode("utf-8", errors="strict")
        total += len(raw)
        rows.append({"path": name, "sha256": sdk.sha(raw), "rawBytes": len(raw)})
    sdk.require(total <= 128 * 1024**2, "outputs")
    return {
        "files": rows,
        "rawBytes": total,
        "inventorySha256": sdk.sha(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        ),
    }


# All fifteen genuine cases, including child navigation, are mandatory.
# Additional cases still need ordinary full-spec success.
REQUIRED_CASES = frozenset(
    "actual Master-free native opaque metadata prototype: " + name
    for name in (
        "fresh_absent",
        "partial_clear_floor",
        "master_absent",
        "master_transition_held",
        "refresh_lock_store",
        "auth_generation_held",
        "logout_held",
        "owner_switch",
        "replaced_database",
        "cancel_held_transaction",
        "foreign_configured_api",
        "foreign_factory_frame",
        "copied_native_event",
        "provider_missing",
        "personal_child_navigation",
    )
)


def browser_case_proof(report):
    observed = {}

    def visit(suites):
        for suite in suites:
            if not isinstance(suite, dict):
                continue
            for spec in suite.get("specs", []):
                if (
                    not isinstance(spec, dict)
                    or spec.get("title") not in REQUIRED_CASES
                ):
                    continue
                for test in spec.get("tests", []):
                    if not isinstance(test, dict):
                        continue
                    results = test.get("results")
                    passed = (
                        test.get("status") == "expected"
                        and isinstance(results, list)
                        and bool(results)
                        and isinstance(results[-1], dict)
                        and results[-1].get("status") == "passed"
                    )
                    observed.setdefault(spec["title"], []).append(passed)
            visit(suite.get("suites", []))

    if isinstance(report, dict) and isinstance(report.get("suites"), list):
        visit(report["suites"])
    complete = set(observed) == REQUIRED_CASES and all(
        values == [True] for values in observed.values()
    )
    return {
        "schemaVersion": 1,
        "feature": FEATURE,
        "requiredCases": sorted(REQUIRED_CASES),
        "observedRequiredCases": len(observed),
        "complete": complete,
        "replayInferenceClaimed": False,
        "activation": False,
    }


# Distinct genuine startup acceptance. The15 existing metadata cases remain
# mandatory in their own singleton profile; neither profile waives the other.
STARTUP_REQUIRED_CASES = frozenset(
    {
        "actual Rust warm cached selection survives held startup beyond ordinary deadline",
        "actual prior profile cache stays usable during monitor auth and clears on real session revocation",
        "actual Rust startup keeps first usable chat independent of expanded metadata",
        "actual native cache version change clears an idle Rust selected view",
    }
)


def startup_browser_case_proof(report):
    observed = {}

    def visit(suites):
        for suite in suites:
            if not isinstance(suite, dict):
                continue
            for spec in suite.get("specs", []):
                if (
                    not isinstance(spec, dict)
                    or spec.get("title") not in STARTUP_REQUIRED_CASES
                ):
                    continue
                entries = observed.setdefault(spec["title"], [])
                entries.append(False)
                tests = spec.get("tests")
                if not isinstance(tests, list) or len(tests) != 1:
                    continue
                test = tests[0]
                results = test.get("results") if isinstance(test, dict) else None
                entries[-1] = (
                    isinstance(test, dict)
                    and test.get("status") == "expected"
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], dict)
                    and results[0].get("status") == "passed"
                    and type(results[0].get("retry")) is int
                    and results[0]["retry"] == 0
                )
            visit(suite.get("suites", []))

    if isinstance(report, dict) and isinstance(report.get("suites"), list):
        visit(report["suites"])
    return {
        "schemaVersion": 1,
        "feature": FEATURE,
        "requiredCases": sorted(STARTUP_REQUIRED_CASES),
        "observedRequiredCases": len(observed),
        "complete": set(observed) == STARTUP_REQUIRED_CASES
        and all(values == [True] for values in observed.values()),
        "replayInferenceClaimed": False,
        "activation": False,
    }


# Separate default-off first-normal-session proof. Old15/startup4 stay held.
FIRST_SESSION_REQUIRED_CASES = frozenset(
    (
        "actual first normal session retains one original Worker through UI and startup",
        "actual revoked first normal session expires once without a Rust restore retry",
        "actual first normal auth queue preserves its original deadline without fallback",
        "actual missing cached Master reads normal Rust session DATA once without private admission",
    )
)


def first_session_browser_case_proof(report):
    observed = {}

    def visit(suites):
        for suite in suites:
            if not isinstance(suite, dict):
                continue
            for spec in suite.get("specs", []):
                if (
                    not isinstance(spec, dict)
                    or spec.get("title") not in FIRST_SESSION_REQUIRED_CASES
                ):
                    continue
                entries = observed.setdefault(spec["title"], [])
                entries.append(False)
                tests = spec.get("tests")
                if not isinstance(tests, list) or len(tests) != 1:
                    continue
                test = tests[0]
                results = test.get("results") if isinstance(test, dict) else None
                entries[-1] = (
                    isinstance(test, dict)
                    and test.get("status") == "expected"
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], dict)
                    and results[0].get("status") == "passed"
                    and type(results[0].get("retry")) is int
                    and results[0]["retry"] == 0
                )
            visit(suite.get("suites", []))

    if isinstance(report, dict) and isinstance(report.get("suites"), list):
        visit(report["suites"])
    return {
        "schemaVersion": 1,
        "feature": FEATURE,
        "requiredCases": sorted(FIRST_SESSION_REQUIRED_CASES),
        "observedRequiredCases": len(observed),
        "complete": set(observed) == FIRST_SESSION_REQUIRED_CASES
        and all(values == [True] for values in observed.values()),
        "replayInferenceClaimed": False,
        "activation": False,
    }


# Partial DATA only; no ACK/retirement/activation is inferred.
NATIVE_RECOVERY_REQUIRED_CASES = frozenset(
    (
        "original native recovery port binds inside genuine restored Worker and drains before root teardown",
        "actual profile native IDB opaque receipt and shared commit: positive",
        "actual profile native IDB opaque receipt and shared commit: uncertain",
        "actual profile native IDB opaque receipt and shared commit: cancel",
        "actual profile native IDB opaque receipt and shared commit: foreign",
        "same native original row Master reread and draft floor hydration: cleared_floor",
        "same native original row Master reread and draft floor hydration: large_draft",
        "same native original row Master reread and draft floor hydration: changed_row",
        "same native original row Master reread and draft floor hydration: cancel_native",
        "same native original row Master reread and draft floor hydration: large_existing_cache",
        "same native original row Master reread and draft floor hydration: cancel_crypto",
        "actual shared metadata Progress cancellation preserves the complete native pending checkpoint and header",
        "same original Core metadata CAS reread and exact journal retirement: success",
        "same original Core metadata CAS reread and exact journal retirement: rewrap_same_key",
        "same original Core metadata CAS reread and exact journal retirement: cancel_read",
        "same original Core metadata CAS reread and exact journal retirement: cancel_write",
        "same original Core metadata CAS reread and exact journal retirement: cancel_reread",
        "same original Core metadata CAS reread and exact journal retirement: journal_race",
        "same original Core metadata CAS reread and exact journal retirement: key_change",
        "same original Core metadata CAS reread and exact journal retirement: profile_negative",
        "same original Core metadata CAS reread and exact journal retirement: unknown_retirement_reply",
        "actual Main recovery metadata remains pending with original journal: success",
        "actual Main recovery metadata remains pending with original journal: cancel_read",
        "actual Main normal canonical alias reply persists with original pending journal: success",
    )
)


def native_recovery_browser_case_proof(report):
    observed = {}

    def visit(suites):
        for suite in suites:
            if not isinstance(suite, dict):
                continue
            for spec in suite.get("specs", []):
                if (
                    not isinstance(spec, dict)
                    or spec.get("title") not in NATIVE_RECOVERY_REQUIRED_CASES
                ):
                    continue
                entries = observed.setdefault(spec["title"], [])
                entries.append(False)
                tests = spec.get("tests")
                if not isinstance(tests, list) or len(tests) != 1:
                    continue
                test = tests[0]
                results = test.get("results") if isinstance(test, dict) else None
                entries[-1] = (
                    isinstance(test, dict)
                    and test.get("status") == "expected"
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], dict)
                    and results[0].get("status") == "passed"
                    and type(results[0].get("retry")) is int
                    and results[0]["retry"] == 0
                )
            visit(suite.get("suites", []))

    if isinstance(report, dict) and isinstance(report.get("suites"), list):
        visit(report["suites"])
    return {
        "schemaVersion": 1,
        "feature": FEATURE,
        "requiredCases": sorted(NATIVE_RECOVERY_REQUIRED_CASES),
        "observedRequiredCases": len(observed),
        "complete": set(observed) == NATIVE_RECOVERY_REQUIRED_CASES
        and all(values == [True] for values in observed.values()),
        "replayInferenceClaimed": False,
        "activation": False,
    }


# Genuine selected send proof only; no activation/full-hint ACK inferred.
ACTIVECHAT_REQUIRED_CASES = frozenset(
    (
        "actual Rust ActiveChat sends follows up and cancels on the original startup owner",
    )
)


def activechat_browser_case_proof(report):
    observed = {}

    def visit(suites):
        for suite in suites:
            if not isinstance(suite, dict):
                continue
            for spec in suite.get("specs", []):
                if (
                    not isinstance(spec, dict)
                    or spec.get("title") not in ACTIVECHAT_REQUIRED_CASES
                ):
                    continue
                entries = observed.setdefault(spec["title"], [])
                entries.append(False)
                tests = spec.get("tests")
                if not isinstance(tests, list) or len(tests) != 1:
                    continue
                test = tests[0]
                results = test.get("results") if isinstance(test, dict) else None
                entries[-1] = (
                    isinstance(test, dict)
                    and test.get("status") == "expected"
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], dict)
                    and results[0].get("status") == "passed"
                    and type(results[0].get("retry")) is int
                    and results[0]["retry"] == 0
                )
            visit(suite.get("suites", []))

    if isinstance(report, dict) and isinstance(report.get("suites"), list):
        visit(report["suites"])
    return {
        "schemaVersion": 1,
        "feature": FEATURE,
        "requiredCases": sorted(ACTIVECHAT_REQUIRED_CASES),
        "observedRequiredCases": len(observed),
        "complete": set(observed) == ACTIVECHAT_REQUIRED_CASES
        and all(values == [True] for values in observed.values()),
        "replayInferenceClaimed": False,
        "activation": False,
    }


# Genuine first request; identity DATA requires actual canonical/native storage.
NEW_CHAT_REQUIRED_CASES = frozenset(
    (
        "actual Rust first request persists before routing then follows up on the original startup owner",
    )
)


def new_chat_browser_case_proof(report):
    observed = {}
    valid_shape = True

    def visit(suites):
        nonlocal valid_shape
        if not isinstance(suites, list):
            valid_shape = False
            return
        for suite in suites:
            if not isinstance(suite, dict) or not isinstance(
                suite.get("specs", []), list
            ):
                valid_shape = False
                continue
            for spec in suite.get("specs", []):
                if (
                    not isinstance(spec, dict)
                    or spec.get("title") not in NEW_CHAT_REQUIRED_CASES
                ):
                    valid_shape = False
                    continue
                entries = observed.setdefault(spec["title"], [])
                entries.append(False)
                tests = spec.get("tests")
                if not isinstance(tests, list) or len(tests) != 1:
                    continue
                test = tests[0]
                results = test.get("results") if isinstance(test, dict) else None
                entries[-1] = (
                    isinstance(test, dict)
                    and test.get("status") == "expected"
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], dict)
                    and results[0].get("status") == "passed"
                    and type(results[0].get("retry")) is int
                    and results[0]["retry"] == 0
                )
            visit(suite.get("suites", []))

    if isinstance(report, dict):
        visit(report.get("suites"))
    else:
        valid_shape = False
    return {
        "schemaVersion": 1,
        "feature": FEATURE,
        "requiredCases": sorted(NEW_CHAT_REQUIRED_CASES),
        "observedRequiredCases": len(observed),
        "complete": valid_shape
        and set(observed) == NEW_CHAT_REQUIRED_CASES
        and all(values == [True] for values in observed.values()),
        "replayInferenceClaimed": False,
        "activation": False,
    }
