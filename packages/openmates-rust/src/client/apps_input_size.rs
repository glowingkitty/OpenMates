//! Count the existing exact JSON-wire bound without retaining a plaintext copy.
//! No async work, client/auth policy, routing, logging or result ownership here.
use super::*;
use std::io::{self, Write};

const MAX_INPUT_BYTES: usize = 1024 * 1024;
#[derive(Default)]
struct InputSize {
    bytes: usize,
    exceeded: bool,
}
impl Write for InputSize {
    fn write(&mut self, chunk: &[u8]) -> io::Result<usize> {
        match self.bytes.checked_add(chunk.len()) {
            Some(total) if total <= MAX_INPUT_BYTES => {
                self.bytes = total;
                Ok(chunk.len())
            }
            _ => {
                self.exceeded = true;
                Err(io::Error::new(io::ErrorKind::InvalidData, "App input size limit"))
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> { Ok(()) }
}
pub(super) fn validate(input: &Value) -> Result<()> {
    let mut size = InputSize::default();
    let encoded = serde_json::to_writer(&mut size, input);
    if size.exceeded {
        return Err(Error::Invalid("App input exceeds the supported limit."));
    }
    encoded.map_err(Error::from)
}

#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=cli.surface.semantic-parity,sdk.encryption.local-only
    #[test]
    fn original_wire_byte_limit_preserves_exact_below_at_above_boundary() {
        let overhead = serde_json::to_vec(&json!({"payload":""})).unwrap().len();
        for (delta, accepted) in [(0usize,true),(1,false)] {
            let input = json!({"payload":"x".repeat(MAX_INPUT_BYTES-overhead+delta)});
            let original = zeroize::Zeroizing::new(serde_json::to_vec(&input).unwrap());
            assert_eq!(original.len(),MAX_INPUT_BYTES+delta);
            assert_eq!(validate(&input).is_ok(),accepted);
            if !accepted {
                assert!(matches!(validate(&input),Err(Error::Invalid("App input exceeds the supported limit."))));
            }
            assert_eq!(input["payload"].as_str().unwrap().len(),MAX_INPUT_BYTES-overhead+delta);
        }
        assert!(validate(&json!({"payload":"x".repeat(MAX_INPUT_BYTES-overhead-1)})).is_ok());
    }
    // contract-test: supporting surface=sdks.rust assertions=cli.surface.semantic-parity,sdk.encryption.local-only
    #[test]
    fn original_serializer_oracle_counts_utf8_and_escaped_wire_bytes() {
        for input in [json!({}),json!({"text":"雪é\n\t\"\\\u{0000}"}),json!({"requests":[{"text":"a"},null,17,true]}),json!({"nested":{"text":"😀"}})] {
            let original=zeroize::Zeroizing::new(serde_json::to_vec(&input).unwrap());
            let mut size=InputSize::default();serde_json::to_writer(&mut size,&input).unwrap();
            assert_eq!(size.bytes,original.len());assert!(!size.exceeded);validate(&input).unwrap();
        }
        // Escaping, not character count, determines the original limit.
        let input=json!({"payload":"\n".repeat(MAX_INPUT_BYTES/2)});
        assert!(input["payload"].as_str().unwrap().len()<MAX_INPUT_BYTES);
        assert!(serde_json::to_vec(&input).unwrap().len()>MAX_INPUT_BYTES);
        assert!(matches!(validate(&input),Err(Error::Invalid("App input exceeds the supported limit."))));
    }
    // contract-test: supporting surface=sdks.rust assertions=cli.surface.semantic-parity,sdk.encryption.local-only
    #[test]
    fn counter_stops_at_limit_and_retains_only_finite_size_state() {
        let mut size=InputSize::default();
        let block=[b'x';4096];
        for _ in 0..MAX_INPUT_BYTES/block.len() {size.write_all(&block).unwrap();}
        assert_eq!(size.bytes,MAX_INPUT_BYTES);assert!(size.write_all(b"x").is_err());assert!(size.exceeded);
        assert_eq!(size.bytes,MAX_INPUT_BYTES);
        assert!(size.write(&[]).is_ok());
        size.bytes=usize::MAX;assert!(size.write(b"x").is_err());assert!(size.exceeded);
    }
}
