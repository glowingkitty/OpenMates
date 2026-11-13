//! C entry of the chat-list seed (`view_fixture_rows`) for the Apple app's
//! DEBUG UI-test fixtures. It is deliberately not a UniFFI export: the
//! committed Swift bindings stay product-only, and only a Swift file compiled
//! under `OPENMATES_CORE_TEST_SUPPORT` declares this symbol, so a library built
//! without the `test-support` feature fails that build at link time instead of
//! silently lacking it. Bytes in, bytes out, no Rust-owned memory crosses.
//! Plan `apple-client-core-migration` (A4).
use crate::CoreError;
use crate::view_fixture_rows::seed_chat_list;

/// The payload was written to `out`; `*out_len` is its length.
pub const SEED_OK: i32 = 0;
/// The request was refused (`CoreError::Invalid`); `out` holds the reason.
pub const SEED_INVALID: i32 = 1;
/// `out` is too small; `*out_len` is the needed capacity and nothing was written.
pub const SEED_BUFFER_TOO_SMALL: i32 = 2;
/// The cache write or encryption failed; `out` holds the error class.
pub const SEED_FAILED: i32 = 3;

/// Writes `bytes` into the caller's buffer (truncated for a message).
///
/// # Safety
/// `out` is valid for `capacity` writable bytes and `out_len` for one write.
unsafe fn write_out(bytes: &[u8], out: *mut u8, capacity: usize, out_len: *mut usize) {
    let length = bytes.len().min(capacity);
    // SAFETY: the caller guarantees `out` holds `capacity` bytes, `length <=
    // capacity`, and Rust-owned `bytes` never overlap the Swift buffer.
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, length);
        *out_len = length;
    }
}

/// Seed the chat list described by the UTF-8 JSON `request` (see
/// `view_fixture_rows::seed_chat_list`) and write the synthetic account's
/// credential payload into `out`. Returns one of the `SEED_*` codes. On
/// `SEED_INVALID` and `SEED_FAILED`, `out` holds a short UTF-8 reason without
/// fixture content. Blocks the calling thread; never call it from inside an
/// async runtime.
///
/// # Safety
/// `request` is valid for `request_len` readable bytes, `out` for
/// `out_capacity` writable bytes and `out_len` for one `usize` write, all for
/// the duration of the call. Null pointers are refused with `SEED_INVALID`
/// (nothing written).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn openmates_test_support_seed_chat_list(
    request: *const u8,
    request_len: usize,
    out: *mut u8,
    out_capacity: usize,
    out_len: *mut usize,
) -> i32 {
    if request.is_null() || out.is_null() || out_len.is_null() {
        return SEED_INVALID;
    }
    // SAFETY: non-null and valid for `request_len` bytes per the contract.
    let request = unsafe { std::slice::from_raw_parts(request, request_len) };
    let (code, bytes) = match seed_chat_list(request) {
        Ok(payload) if payload.len() > out_capacity => {
            // SAFETY: `out_len` is non-null and writable per the contract.
            unsafe { *out_len = payload.len() };
            return SEED_BUFFER_TOO_SMALL;
        }
        Ok(payload) => (SEED_OK, payload),
        Err(CoreError::Invalid { message }) => (SEED_INVALID, message.into_bytes()),
        Err(error) => (SEED_FAILED, format!("{error:?}").into_bytes()),
    };
    // SAFETY: the buffers are valid per this function's contract.
    unsafe { write_out(&bytes, out, out_capacity, out_len) };
    code
}
