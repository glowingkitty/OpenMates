# Temporary Ristretto255-only forks of `voprf` 0.5.0 and `opaque-ke` 4.0.0

Purpose: remove `elliptic-curve` 0.13 and its unpatched `crypto-bigint` 0.5.5
(RUSTSEC-2026-0387, patched only in 0.7.6+) from every OpenMates Rust lockfile.
OpenMates uses only the Ristretto255 / TripleDH(Ristretto255, SHA-512) suite
(`packages/openmates-rust/src/pairing.rs`), which never needed elliptic-curve
arithmetic.

Base: upstream tags `facebook/voprf` v0.5.0 (f0531f0812387cd6be01923b21e2157399a9b295)
and `facebook/opaque-ke` v4.0.0 (ed5e7cf116a3786bb6c237eaf06159137f4d0ba3).

Changes (no protocol, suite, KSF or serialization change):
- voprf: removed the `elliptic-curve` dependency, the generic NIST `Group` impl
  (`group/elliptic_curve.rs`) and the `VoprfParameters` blanket `CipherSuite` impl;
  `expand_message_xmd` is vendored verbatim from elliptic-curve 0.13.8 with its
  RFC 9380 vectors (`src/expand_msg.rs`).
- opaque-ke: removed the `elliptic-curve`, `ecdsa` and `rfc6979` dependencies, the
  generic NIST key-exchange group and the `ecdsa` feature.
- Tests: NIST-curve cases removed; Ristretto255 RFC 9497 / RFC 9807 vectors kept.

Consumed through `[patch.crates-io]` in each Rust package manifest. Delete this
directory and the patch sections once upstream releases a voprf/opaque-ke that no
longer depends on elliptic-curve 0.13 (or crypto-bigint < 0.7.6).
