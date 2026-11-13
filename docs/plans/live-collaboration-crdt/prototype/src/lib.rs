//! Phase 0 spike for plan `live-collaboration-crdt` (spec `feature.live-collaboration@1`).
//! Standalone scratch crate, not part of `openmates-sdk`: it proves that Yjs-format
//! documents built with `yrs` can carry a doc, a sheet and a deck, exchange
//! individually encrypted update packets, converge, and absorb an assistant text diff
//! as a minimal change set. Findings and the recommendation are in `../spike.md`.

pub mod diff_apply;
pub mod envelope;
pub mod model;
