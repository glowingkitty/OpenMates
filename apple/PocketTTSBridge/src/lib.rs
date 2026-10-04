//! Private developer-lab C ABI. No HTTP, provider fallback, input/output logging.
//! A caller owns one engine, calls it serially and destroys it after synthesis.
use pocket_tts_ios::{PocketTTSEngine, tokenizer::PocketTokenizer};
use std::{ffi::{c_char, CStr}, panic::{catch_unwind, AssertUnwindSafe}, ptr};

pub struct Engine { model: PocketTTSEngine, tokenizer: PocketTokenizer }
pub struct Audio { wav: Vec<u8> }
const MAX_SENTENCE_BYTES: usize = 160;
const MAX_TOKENS: usize = 64;
const MAX_WAV_BYTES: usize = 4 * 1024 * 1024;

/// Returns null for invalid/unloadable assets. Errors never contain private data.
#[no_mangle]
pub unsafe extern "C" fn om_pocket_create(path: *const c_char) -> *mut Engine {
    if path.is_null() { return ptr::null_mut(); }
    catch_unwind(AssertUnwindSafe(|| {
        let path = CStr::from_ptr(path).to_str().ok()?;
        if path.len() > 4096 { return None; }
        let tokenizer = PocketTokenizer::from_file(std::path::Path::new(path).join("tokenizer.model")).ok()?;
        let model = PocketTTSEngine::new(path.to_owned()).ok()?;
        Some(Box::into_raw(Box::new(Engine { model, tokenizer })))
    })).ok().flatten().unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn om_pocket_synthesize(engine: *mut Engine, text: *const c_char) -> *mut Audio {
    if engine.is_null() || text.is_null() { return ptr::null_mut(); }
    catch_unwind(AssertUnwindSafe(|| {
        let text = CStr::from_ptr(text).to_str().ok()?;
        if text.trim().is_empty() || text.len() > MAX_SENTENCE_BYTES { return None; }
        let engine = &*engine;
        let tokens = engine.tokenizer.encode(text).ok()?;
        if tokens.is_empty() || tokens.len() > MAX_TOKENS { return None; }
        // Index zero is the only installed and licensed voice: Alba (CC BY 4.0).
        let result = engine.model.synthesize(text.to_owned()).ok()?;
        if result.sample_rate != 24000 || result.channels != 1 || result.audio_data.len() > MAX_WAV_BYTES
            || !result.duration_seconds.is_finite() || result.duration_seconds <= 0.0 || result.duration_seconds > 80.0 {
            return None;
        }
        Some(Box::into_raw(Box::new(Audio { wav: result.audio_data })))
    })).ok().flatten().unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn om_pocket_audio_bytes(audio: *const Audio) -> *const u8 {
    if audio.is_null() { return ptr::null(); }
    (*audio).wav.as_ptr()
}
#[no_mangle]
pub unsafe extern "C" fn om_pocket_audio_count(audio: *const Audio) -> usize {
    if audio.is_null() { return 0; }
    (*audio).wav.len()
}
#[no_mangle]
pub unsafe extern "C" fn om_pocket_audio_free(audio: *mut Audio) {
    if !audio.is_null() { drop(Box::from_raw(audio)); }
}
#[no_mangle]
pub unsafe extern "C" fn om_pocket_destroy(engine: *mut Engine) {
    if !engine.is_null() {
        let engine = Box::from_raw(engine);
        // A prior caught kernel panic may poison its Mutex. Never unwind into Swift.
        let _ = catch_unwind(AssertUnwindSafe(|| engine.model.unload()));
        drop(engine);
    }
}
