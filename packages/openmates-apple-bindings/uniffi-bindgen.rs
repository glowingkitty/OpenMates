//! Host-only UniFFI Swift generator for this crate: the standard
//! `uniffi-bindgen-swift` CLI built from the same pinned `uniffi` release as the
//! scaffolding, so generated Swift and the static library always agree.
//! Built with `--features bindgen`; used by `build-xcframework.sh` in library mode.
fn main() {
    uniffi::uniffi_bindgen_swift()
}
