//! Isolated actual CPU smoke. Only a fixed public phrase; no app/account data.
use openmates_pocket_tts::{om_pocket_create, om_pocket_synthesize, om_pocket_audio_bytes,
    om_pocket_audio_count, om_pocket_audio_free, om_pocket_destroy};
use std::{ffi::CString, time::Instant};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::var("POCKET_MODEL_ROOT")?;
    let output = std::env::var("POCKET_SMOKE_WAV")?;
    let started = Instant::now();
    let path = CString::new(root)?;
    let text = CString::new("The quick brown fox jumps over the lazy dog.")?;
    unsafe {
        let engine = om_pocket_create(path.as_ptr());
        if engine.is_null() { return Err("Pocket load failed".into()); }
        let loaded = started.elapsed();
        let audio = om_pocket_synthesize(engine, text.as_ptr());
        if audio.is_null() { om_pocket_destroy(engine); return Err("Pocket synthesis failed".into()); }
        let count = om_pocket_audio_count(audio);
        let data = std::slice::from_raw_parts(om_pocket_audio_bytes(audio), count);
        let saved = std::fs::write(output, data);
        om_pocket_audio_free(audio); om_pocket_destroy(engine);
        saved?;
        println!("load_ms={} total_ms={} wav_bytes={}", loaded.as_millis(), started.elapsed().as_millis(), count);
    }
    Ok(())
}
