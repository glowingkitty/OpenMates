fn main() {
    #[cfg(feature = "napi-bindings")]
    napi_build::setup();
}
