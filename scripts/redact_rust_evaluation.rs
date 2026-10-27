//! Standalone synthetic native benchmark. Build with rustc --edition=2021 -O.
//! No subprocess performs model work; SDK licensing remains intact.
use std::collections::{HashMap, HashSet};
use std::ffi::{c_char, c_int, c_long, c_void, CStr, CString};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
use std::sync::OnceLock;
use std::time::Instant;

type Res<T> = Result<T, &'static str>;
const MAX_INPUT: usize = 16 * 1024 * 1024;
const MAX_TEXT: usize = 1024 * 1024;
const MAX_RESULT: usize = 32 * 1024 * 1024;
const STAGES: [&str; 9] = [
    "arguments",
    "native-preflight",
    "create",
    "download",
    "license-flush",
    "network-seal",
    "read-input",
    "classification",
    "write-receipt",
];
static STAGE: AtomicU8 = AtomicU8::new(0);
static LICENSE_CALLS: AtomicU64 = AtomicU64::new(0);
static LICENSE_VALID: AtomicU64 = AtomicU64::new(0);
static OUTPUT_OWNED: AtomicBool = AtomicBool::new(false);
static CASE_RECEIPT_SAVED: AtomicBool = AtomicBool::new(false);
static DISCONNECTED_SOCKETS: AtomicU64 = AtomicU64::new(0);

#[link(name = "dl")]
unsafe extern "C" {
    fn dlopen(name: *const c_char, flags: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, name: *const c_char) -> *mut c_void;
    fn dladdr(address: *const c_void, info: *mut DlInfo) -> c_int;
    fn socket(domain: c_int, kind: c_int, protocol: c_int) -> c_int;
    fn close(fd: c_int) -> c_int;
    fn shutdown(fd: c_int, how: c_int) -> c_int;
    fn send(fd: c_int, buffer: *const c_void, length: usize, flags: c_int) -> isize;
    fn recv(fd: c_int, buffer: *mut c_void, length: usize, flags: c_int) -> isize;
    fn getsockopt(
        fd: c_int,
        level: c_int,
        option: c_int,
        value: *mut c_void,
        length: *mut u32,
    ) -> c_int;
    fn __errno_location() -> *mut c_int;
}
#[repr(C)]
struct DlInfo {
    filename: *const c_char,
    base: *mut c_void,
    symbol: *const c_char,
    symbol_address: *mut c_void,
}

// Handles deliberately remain loaded for process lifetime (the SDK embeds Swift).
fn library(name: &str, flags: c_int) -> Res<usize> {
    let name = CString::new(name).map_err(|_| "invalid-library-path")?;
    let ptr = unsafe { dlopen(name.as_ptr(), flags) };
    if ptr.is_null() {
        Err("native-library-unavailable")
    } else {
        Ok(ptr as usize)
    }
}
unsafe fn symbol<T: Copy>(handle: usize, name: &str) -> Res<T> {
    if std::mem::size_of::<T>() != std::mem::size_of::<*mut c_void>() {
        return Err("invalid-function-pointer-size");
    }
    let name = CString::new(name).map_err(|_| "invalid-symbol-name")?;
    let ptr = unsafe { dlsym(handle as *mut c_void, name.as_ptr()) };
    if ptr.is_null() {
        return Err("native-symbol-unavailable");
    }
    Ok(unsafe { std::mem::transmute_copy(&ptr) })
}
fn mapped_symbol(handle: usize, name: &str) -> Res<(usize, PathBuf)> {
    let name = CString::new(name).map_err(|_| "invalid-symbol-name")?;
    let ptr = unsafe { dlsym(handle as *mut c_void, name.as_ptr()) };
    if ptr.is_null() {
        return Err("decoder-symbol-missing");
    }
    let mut info = DlInfo {
        filename: std::ptr::null(),
        base: std::ptr::null_mut(),
        symbol: std::ptr::null(),
        symbol_address: std::ptr::null_mut(),
    };
    if unsafe { dladdr(ptr, &mut info) } == 0 || info.filename.is_null() {
        return Err("decoder-address-unmapped");
    }
    let filename = unsafe { CStr::from_ptr(info.filename) }
        .to_str()
        .map_err(|_| "invalid-library-name")?;
    Ok((
        ptr as usize,
        fs::canonicalize(filename).map_err(|_| "decoder-path-unavailable")?,
    ))
}

type MdNew = unsafe extern "C" fn() -> *mut c_void;
type MdFree = unsafe extern "C" fn(*mut c_void);
type Sha256 = unsafe extern "C" fn() -> *const c_void;
type D2iKey = unsafe extern "C" fn(*mut *mut c_void, *mut *const u8, c_long) -> *mut c_void;
type VerifyInit = unsafe extern "C" fn(
    *mut c_void,
    *mut *mut c_void,
    *const c_void,
    *mut c_void,
    *mut c_void,
) -> c_int;
type Verify = unsafe extern "C" fn(*mut c_void, *const u8, usize, *const u8, usize) -> c_int;
struct OpenSsl {
    _handle: usize,
    md_new: MdNew,
    md_free: MdFree,
    sha256: Sha256,
    read_key: D2iKey,
    key_free: MdFree,
    init: VerifyInit,
    verify: Verify,
}
impl OpenSsl {
    fn load() -> Res<Self> {
        let handle = library("libcrypto.so.3", 2)?;
        unsafe {
            Ok(Self {
                _handle: handle,
                md_new: symbol(handle, "EVP_MD_CTX_new")?,
                md_free: symbol(handle, "EVP_MD_CTX_free")?,
                sha256: symbol(handle, "EVP_sha256")?,
                read_key: symbol(handle, "d2i_PUBKEY")?,
                key_free: symbol(handle, "EVP_PKEY_free")?,
                init: symbol(handle, "EVP_DigestVerifyInit")?,
                verify: symbol(handle, "EVP_DigestVerify")?,
            })
        }
    }
}
static SSL: OnceLock<Res<OpenSsl>> = OnceLock::new();
fn openssl() -> Res<&'static OpenSsl> {
    SSL.get_or_init(OpenSsl::load).as_ref().map_err(|e| *e)
}

fn p1363_der(raw: &[u8]) -> Res<Vec<u8>> {
    if raw.len() != 64 {
        return Err("invalid-es256-signature-size");
    }
    let mut body = Vec::with_capacity(70);
    for integer in [&raw[..32], &raw[32..]] {
        let first = integer.iter().position(|b| *b != 0).unwrap_or(31);
        let value = &integer[first..];
        let pad = value[0] & 0x80 != 0;
        body.push(2);
        body.push((value.len() + usize::from(pad)) as u8);
        if pad {
            body.push(0);
        }
        body.extend_from_slice(value);
    }
    let mut out = vec![0x30, body.len() as u8];
    out.extend(body);
    Ok(out)
}
fn verify_es256(signature: &[u8], message: &[u8], public_key: &[u8]) -> bool {
    if signature.len() != 64
        || public_key.len() != 65
        || public_key[0] != 4
        || message.len() > MAX_TEXT
    {
        return false;
    }
    let Ok(ssl) = openssl() else {
        return false;
    };
    let Ok(der_signature) = p1363_der(signature) else {
        return false;
    };
    let mut spki = vec![
        0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01, 0x06, 0x08,
        0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00,
    ];
    spki.extend_from_slice(public_key);
    unsafe {
        let mut cursor = spki.as_ptr();
        let key = (ssl.read_key)(std::ptr::null_mut(), &mut cursor, spki.len() as c_long);
        if key.is_null() {
            return false;
        }
        let ctx = (ssl.md_new)();
        if ctx.is_null() {
            (ssl.key_free)(key);
            return false;
        }
        let valid = (ssl.init)(
            ctx,
            std::ptr::null_mut(),
            (ssl.sha256)(),
            std::ptr::null_mut(),
            key,
        ) == 1
            && (ssl.verify)(
                ctx,
                der_signature.as_ptr(),
                der_signature.len(),
                message.as_ptr(),
                message.len(),
            ) == 1;
        (ssl.md_free)(ctx);
        (ssl.key_free)(key);
        valid
    }
}
unsafe extern "C" fn license_verifier(
    sig: *const u8,
    sig_len: i32,
    msg: *const u8,
    msg_len: i32,
    key: *const u8,
    key_len: i32,
) -> i32 {
    LICENSE_CALLS.fetch_add(1, Ordering::Relaxed);
    let verified = std::panic::catch_unwind(|| {
        if sig.is_null()
            || msg.is_null()
            || key.is_null()
            || sig_len != 64
            || key_len != 65
            || msg_len < 0
            || msg_len as usize > MAX_TEXT
        {
            return false;
        }
        unsafe {
            verify_es256(
                std::slice::from_raw_parts(sig, 64),
                std::slice::from_raw_parts(msg, msg_len as usize),
                std::slice::from_raw_parts(key, 65),
            )
        }
    })
    .unwrap_or(false);
    if verified {
        LICENSE_VALID.fetch_add(1, Ordering::Relaxed);
        1
    } else {
        0
    }
}

type LicenseCallback = unsafe extern "C" fn(*const u8, i32, *const u8, i32, *const u8, i32) -> i32;
type Create = unsafe extern "C" fn(*const c_char, *const c_char, *const c_char) -> *mut c_void;
type Download = unsafe extern "C" fn(*mut c_void) -> i32;
type Run = unsafe extern "C" fn(
    *mut c_void,
    *const u8,
    i32,
    *const u8,
    i32,
    *const c_char,
    *const c_char,
) -> *mut u8;
type BufferFree = unsafe extern "C" fn(*mut u8);
type Destroy = unsafe extern "C" fn(*mut c_void);
type Flush = unsafe extern "C" fn();
struct Api {
    create: Create,
    download: Download,
    run: Run,
    free: BufferFree,
    destroy: Destroy,
    flush: Flush,
}
struct NativeProof {
    version_address: usize,
    decoder_address: usize,
    decoder_path: String,
}
fn native_api(native: &Path) -> Res<(Api, NativeProof)> {
    for key in ["LD_PRELOAD", "LD_AUDIT"] {
        if std::env::var_os(key).is_some_and(|s| !s.is_empty()) {
            return Err("loader-interposition-forbidden");
        }
    }
    let prefix = std::env::var_os("OPENMATES_REDACT_BROTLI_PREFIX")
        .ok_or("patched-brotli-prefix-required")?;
    let prefix = fs::canonicalize(prefix).map_err(|_| "patched-brotli-prefix-missing")?;
    let private = prefix.join("lib");
    if std::env::var_os("LD_LIBRARY_PATH").as_deref() != Some(private.as_os_str()) {
        return Err("private-decoder-loader-path-required");
    }
    library(
        native
            .join("libLiteRt.so")
            .to_str()
            .ok_or("invalid-native-path")?,
        2,
    )?;
    let core = library(
        native
            .join("libRedactNode.so")
            .to_str()
            .ok_or("invalid-native-path")?,
        2,
    )?;
    let available: unsafe extern "C" fn() -> i32 = unsafe { symbol(core, "dal_curl_available")? };
    if unsafe { available() } != 1 {
        return Err("native-curl-shim-unavailable");
    }
    let curl = library("libcurl.so.4", 2 | 4)?; // existing shim-loaded handle only
    let version: unsafe extern "C" fn() -> u32 = unsafe { symbol(curl, "BrotliDecoderVersion")? };
    if unsafe { version() } != 16_781_313 {
        return Err("unpatched-brotli-version");
    }
    let (version_address, version_path) = mapped_symbol(curl, "BrotliDecoderVersion")?;
    let (decoder_address, decoder_path) = mapped_symbol(curl, "BrotliDecoderDecompressStream")?;
    if version_path != decoder_path || !decoder_path.starts_with(&private) {
        return Err("decoder-outside-verified-prefix");
    }
    for line in fs::read_to_string("/proc/self/maps")
        .map_err(|_| "process-maps-unavailable")?
        .lines()
        .filter(|line| line.contains("/libbrotli"))
    {
        let file = line
            .split_whitespace()
            .last()
            .ok_or("invalid-process-map")?;
        if !fs::canonicalize(file)
            .map_err(|_| "invalid-brotli-map")?
            .starts_with(&private)
        {
            return Err("system-brotli-mapped");
        }
    }
    openssl()?;
    let install: unsafe extern "C" fn(Option<LicenseCallback>) -> i32 =
        unsafe { symbol(core, "dal_set_license_verifier")? };
    if unsafe { install(Some(license_verifier)) } != 0 {
        return Err("license-verifier-install-failed");
    }
    unsafe {
        Ok((
            Api {
                create: symbol(core, "redact_create")?,
                download: symbol(core, "dal_download")?,
                run: symbol(core, "dal_run")?,
                free: symbol(core, "dal_buffer_free")?,
                destroy: symbol(core, "dal_destroy")?,
                flush: symbol(core, "dal_flush_telemetry")?,
            },
            NativeProof {
                version_address,
                decoder_address,
                decoder_path: decoder_path.to_string_lossy().into_owned(),
            },
        ))
    }
}
struct Model {
    pointer: *mut c_void,
    destroy: Destroy,
}
impl Drop for Model {
    fn drop(&mut self) {
        unsafe {
            (self.destroy)(self.pointer);
        }
    }
}
struct Buffer {
    pointer: *mut u8,
    free: BufferFree,
}
impl Drop for Buffer {
    fn drop(&mut self) {
        unsafe {
            (self.free)(self.pointer);
        }
    }
}

#[derive(Clone)]
struct InternetSocket {
    fd: i32,
    inode: String,
    tcp: bool,
}
struct DisconnectedSocket {
    socket: InternetSocket,
    tcp_state: u8,
}
struct NetworkProof {
    disconnected: Vec<DisconnectedSocket>,
    retained_descriptors: usize,
}

fn owned_internet_sockets() -> Res<Vec<InternetSocket>> {
    let mut owned = Vec::new();
    for fd in fs::read_dir("/proc/self/fd").map_err(|_| "fd-inventory-unavailable")? {
        let fd = fd.map_err(|_| "fd-inventory-unavailable")?;
        if let Ok(link) = fs::read_link(fd.path()) {
            let name = link.to_string_lossy();
            if let Some(id) = name
                .strip_prefix("socket:[")
                .and_then(|s| s.strip_suffix(']'))
            {
                let number = fd
                    .file_name()
                    .to_string_lossy()
                    .parse::<i32>()
                    .map_err(|_| "invalid-socket-fd")?;
                owned.push((number, id.to_owned()));
            }
        }
    }
    let mut found = Vec::new();
    for name in [
        "tcp", "tcp6", "udp", "udp6", "raw", "raw6", "udplite", "udplite6",
    ] {
        let file = PathBuf::from("/proc/self/net").join(name);
        if !file.exists() {
            if ["tcp", "tcp6", "udp", "udp6"].contains(&name) {
                return Err("internet-socket-inventory-unavailable");
            } else {
                continue;
            }
        }
        for line in fs::read_to_string(file)
            .map_err(|_| "internet-socket-inventory-unavailable")?
            .lines()
            .skip(1)
        {
            if let Some(inode) = line.split_whitespace().nth(9) {
                for (fd, owned_inode) in &owned {
                    if owned_inode == inode {
                        found.push(InternetSocket {
                            fd: *fd,
                            inode: inode.to_owned(),
                            tcp: name.starts_with("tcp"),
                        });
                    }
                }
            }
        }
    }
    Ok(found)
}

fn verify_disconnected_socket(socket: &InternetSocket, sealed: bool) -> Res<u8> {
    let actual = fs::read_link(format!("/proc/self/fd/{}", socket.fd))
        .map_err(|_| "disconnected-descriptor-disappeared")?;
    if actual.to_string_lossy() != format!("socket:[{}]", socket.inode) {
        return Err("licensing-socket-descriptor-reused");
    }
    if !socket.tcp {
        return Err("unsupported-non-tcp-licensing-socket");
    }
    let mut info = [0u8; 256];
    let mut length = info.len() as u32;
    // Linux TCP_INFO exposes the actual TCP state; getpeername alone can still
    // report a peer after shutdown and is deliberately not used as proof.
    if unsafe { getsockopt(socket.fd, 6, 11, info.as_mut_ptr().cast(), &mut length) } != 0
        || length < 1
    {
        return Err("disconnected-tcp-state-unavailable");
    }
    if ![4u8, 5, 6, 7, 9, 11].contains(&info[0]) {
        return Err("internet-socket-still-active-after-shutdown");
    }
    // Zero bytes cannot send application data even if this check fails. Before
    // sealing, shutdown must reject the write itself; afterward EPERM is also
    // expected from the OS network filter.
    let sent = unsafe { send(socket.fd, std::ptr::null(), 0, 0x4000 | 0x40) }; // NOSIGNAL | DONTWAIT
    let send_errno = unsafe { *__errno_location() };
    if sent != -1 || !([32, 104, 107].contains(&send_errno) || sealed && send_errno == 1) {
        return Err("shutdown-did-not-disable-socket-writes");
    }
    let mut byte = 0u8;
    let read = unsafe { recv(socket.fd, (&mut byte as *mut u8).cast(), 1, 0x2 | 0x40) }; // PEEK | DONTWAIT
    let read_errno = unsafe { *__errno_location() };
    if read != 0 && !(read == -1 && [104, 107].contains(&read_errno)) {
        return Err("shutdown-socket-not-at-read-eof");
    }
    Ok(info[0])
}

fn shutdown_licensing_socket(socket: &InternetSocket) -> Res<DisconnectedSocket> {
    if !socket.tcp {
        return Err("unsupported-non-tcp-licensing-socket");
    }
    let actual = fs::read_link(format!("/proc/self/fd/{}", socket.fd))
        .map_err(|_| "licensing-socket-disappeared-before-shutdown")?;
    if actual.to_string_lossy() != format!("socket:[{}]", socket.inode) {
        return Err("licensing-socket-descriptor-reused");
    }
    // Deliberately simulate loss of networking after the SDK's normal license
    // flush. Never close or reuse a descriptor owned by the SDK/libcurl.
    if unsafe { shutdown(socket.fd, 2) } != 0 {
        return Err("licensing-socket-shutdown-failed");
    }
    let tcp_state = verify_disconnected_socket(socket, false)?;
    Ok(DisconnectedSocket {
        socket: socket.clone(),
        tcp_state,
    })
}

fn assert_no_active_internet(disconnected: &[DisconnectedSocket], sealed: bool) -> Res<usize> {
    let sockets = owned_internet_sockets()?;
    for socket in &sockets {
        if !disconnected
            .iter()
            .any(|proof| proof.socket.inode == socket.inode)
        {
            return Err("untracked-internet-socket-at-seal");
        }
        verify_disconnected_socket(socket, sealed)?;
    }
    Ok(sockets.len())
}

fn seal_network() -> Res<NetworkProof> {
    let mut disconnected = Vec::new();
    let mut seen = HashSet::new();
    for socket in owned_internet_sockets()? {
        if seen.insert(socket.inode.clone()) {
            disconnected.push(shutdown_licensing_socket(&socket)?);
            DISCONNECTED_SOCKETS.fetch_add(1, Ordering::Relaxed);
        }
    }
    assert_no_active_internet(&disconnected, false)?;
    let lib = library("libseccomp.so.2", 2)?;
    unsafe {
        let init: unsafe extern "C" fn(u32) -> *mut c_void = symbol(lib, "seccomp_init")?;
        let attr: unsafe extern "C" fn(*mut c_void, i32, u32) -> i32 =
            symbol(lib, "seccomp_attr_set")?;
        let resolve: unsafe extern "C" fn(*const c_char) -> i32 =
            symbol(lib, "seccomp_syscall_resolve_name")?;
        let add: unsafe extern "C" fn(*mut c_void, u32, i32, u32) -> i32 =
            symbol(lib, "seccomp_rule_add")?;
        let load: unsafe extern "C" fn(*mut c_void) -> i32 = symbol(lib, "seccomp_load")?;
        let release: unsafe extern "C" fn(*mut c_void) = symbol(lib, "seccomp_release")?;
        let context = init(0x7fff0000);
        if context.is_null() {
            return Err("seccomp-init-failed");
        }
        let applied = (|| {
            if attr(context, 4, 1) != 0 {
                return Err("seccomp-tsync-unavailable");
            }
            for name in [
                "socket",
                "socketpair",
                "connect",
                "sendto",
                "sendmsg",
                "sendmmsg",
            ] {
                let name = CString::new(name).map_err(|_| "invalid-syscall-name")?;
                let number = resolve(name.as_ptr());
                if number < 0 || add(context, 0x00050001, number, 0) != 0 {
                    return Err("seccomp-rule-failed");
                }
            }
            if load(context) != 0 {
                return Err("seccomp-load-failed");
            }
            Ok(())
        })();
        release(context);
        applied?;
        let fd = socket(2, 1, 0);
        let denied = fd == -1 && *__errno_location() == 1;
        if fd >= 0 {
            close(fd);
        }
        if !denied {
            return Err("seccomp-socket-self-test-failed");
        }
    }
    let retained_descriptors = assert_no_active_internet(&disconnected, true)?;
    Ok(NetworkProof {
        disconnected,
        retained_descriptors,
    })
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn take(&mut self, n: usize) -> Res<&'a [u8]> {
        let end = self.offset.checked_add(n).ok_or("codec-length-overflow")?;
        let value = self.bytes.get(self.offset..end).ok_or("codec-truncated")?;
        self.offset = end;
        Ok(value)
    }
    fn u32(&mut self) -> Res<u32> {
        Ok(u32::from_be_bytes(
            self.take(4)?.try_into().map_err(|_| "codec-u32")?,
        ))
    }
    fn f64(&mut self) -> Res<f64> {
        Ok(f64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| "codec-f64")?,
        ))
    }
    fn string(&mut self, cap: usize) -> Res<&'a str> {
        let length = self.u32()? as usize;
        if length > cap {
            return Err("codec-string-limit");
        }
        std::str::from_utf8(self.take(length)?).map_err(|_| "codec-invalid-utf8")
    }
    fn finished(&self) -> Res<()> {
        if self.offset == self.bytes.len() {
            Ok(())
        } else {
            Err("codec-trailing-bytes")
        }
    }
}
fn push_string(out: &mut Vec<u8>, text: &str) -> Res<()> {
    let len = u32::try_from(text.len()).map_err(|_| "codec-string-limit")?;
    out.extend_from_slice(&len.to_be_bytes());
    out.extend_from_slice(text.as_bytes());
    Ok(())
}
struct Input {
    id: String,
    text: String,
}
fn parse_inputs(bytes: &[u8]) -> Res<Vec<Input>> {
    if bytes.len() > MAX_INPUT {
        return Err("input-file-limit");
    }
    let mut cursor = Cursor::new(bytes);
    let count = cursor.u32()? as usize;
    if count == 0 || count > 256 {
        return Err("input-case-count-limit");
    }
    let mut out = Vec::with_capacity(count);
    let mut ids = HashSet::new();
    for _ in 0..count {
        let id = cursor.string(128)?;
        if !(id.starts_with("q:") || id.starts_with("lat:"))
            || id.is_empty()
            || !id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-:".contains(&b))
            || !ids.insert(id.to_owned())
        {
            return Err("invalid-or-duplicate-case-id");
        }
        let text = cursor.string(MAX_TEXT)?.to_owned();
        out.push(Input {
            id: id.to_owned(),
            text,
        });
    }
    cursor.finished()?;
    Ok(out)
}
#[derive(Clone, Debug)]
struct Span {
    label: String,
    start: u32,
    end: u32,
    confidence: f64,
}
fn validate_original(units: &[u16], start: u32, end: u32, original: &str) -> Res<()> {
    let (start, end) = (start as usize, end as usize);
    if start >= end || end > units.len() {
        return Err("invalid-utf16-span");
    }
    let split = |i: usize| {
        i > 0
            && i < units.len()
            && (0xd800..=0xdbff).contains(&units[i - 1])
            && (0xdc00..=0xdfff).contains(&units[i])
    };
    if split(start)
        || split(end)
        || String::from_utf16(&units[start..end]).map_err(|_| "invalid-utf16-span")? != original
    {
        return Err("invalid-original-offset-integrity");
    }
    Ok(())
}
fn parse_result(payload: &[u8], text: &str) -> Res<Vec<Span>> {
    let mut cursor = Cursor::new(payload);
    let redacted_text = cursor.string(MAX_RESULT)?; // memory only, never saved/logged
    let count = cursor.u32()? as usize;
    if count > 65_536 {
        return Err("result-item-limit");
    }
    let units: Vec<u16> = text.encode_utf16().collect();
    let mut spans = Vec::with_capacity(count);
    let mut expected_redacted = Vec::new();
    let mut mappings = Vec::with_capacity(count);
    let mut placeholders = HashSet::new();
    let mut counts: HashMap<&str, u32> = HashMap::new();
    let mut previous_end = 0;
    for _ in 0..count {
        let label = cursor.string(64)?;
        if label.is_empty() || !label.bytes().all(|b| b.is_ascii_uppercase() || b == b'_') {
            return Err("invalid-result-label");
        }
        let original = cursor.string(MAX_TEXT)?;
        let placeholder = cursor.string(256)?; // memory only, never saved/logged
        let confidence = cursor.f64()?;
        let start = cursor.u32()?;
        let end = cursor.u32()?;
        if !confidence.is_finite() || !(0.0..=1.0).contains(&confidence) || start < previous_end {
            return Err("invalid-result-order-or-confidence");
        }
        validate_original(&units, start, end, original)?;
        let counter = counts.entry(label).or_insert(0);
        *counter = counter.checked_add(1).ok_or("placeholder-count-overflow")?;
        if placeholder != format!("[{label}_{counter}]") {
            return Err("invalid-sdk-placeholder");
        }
        if !placeholders.insert(placeholder) || text.contains(placeholder) {
            return Err("ambiguous-placeholder-mapping");
        }
        expected_redacted.extend_from_slice(&units[previous_end as usize..start as usize]);
        expected_redacted.extend(placeholder.encode_utf16());
        if expected_redacted.len() > MAX_RESULT {
            return Err("redacted-reconstruction-limit");
        }
        mappings.push((placeholder, original));
        previous_end = end;
        spans.push(Span {
            label: label.to_owned(),
            start,
            end,
            confidence,
        });
    }
    cursor.finished()?;
    expected_redacted.extend_from_slice(&units[previous_end as usize..]);
    if String::from_utf16(&expected_redacted)
        .map_err(|_| "redacted-reconstruction-invalid-utf16")?
        != redacted_text
    {
        return Err("sdk-redacted-text-mismatch");
    }
    // Match Redact.restore's ordered, literal replace-all semantics exactly.
    // Unique tokens absent from the original prevent aliasing and cascades.
    let mut restored = redacted_text.to_owned();
    for (placeholder, original) in mappings {
        if restored.matches(placeholder).count() != 1 {
            return Err("ambiguous-placeholder-mapping");
        }
        let size = restored
            .len()
            .checked_sub(placeholder.len())
            .and_then(|n| n.checked_add(original.len()))
            .ok_or("restoration-size-overflow")?;
        if size > MAX_RESULT {
            return Err("restoration-size-limit");
        }
        restored = restored.replace(placeholder, original);
    }
    if restored != text {
        return Err("sdk-restoration-mismatch");
    }
    Ok(spans)
}
fn classify(api: &Api, model: &Model, text: &str, options: &[u8]) -> Res<Vec<Span>> {
    let mut input = Vec::with_capacity(text.len() + 4);
    push_string(&mut input, text)?;
    let length = i32::try_from(input.len()).map_err(|_| "input-length-limit")?;
    let options_length = i32::try_from(options.len()).map_err(|_| "options-length-limit")?;
    let pointer = unsafe {
        (api.run)(
            model.pointer,
            input.as_ptr(),
            length,
            options.as_ptr(),
            options_length,
            std::ptr::null(),
            std::ptr::null(),
        )
    };
    if pointer.is_null() {
        return Err("sdk-run-failed");
    }
    let buffer = Buffer {
        pointer,
        free: api.free,
    };
    let header = unsafe { std::slice::from_raw_parts(buffer.pointer, 4) };
    let length = u32::from_be_bytes(header.try_into().map_err(|_| "result-framing")?) as usize;
    if length > MAX_RESULT {
        return Err("result-size-limit");
    }
    let payload = unsafe { std::slice::from_raw_parts(buffer.pointer.add(4), length) };
    parse_result(payload, text)
}
fn options() -> Res<Vec<u8>> {
    let labels = [
        "GIVEN_NAME",
        "SURNAME",
        "STREET_NAME",
        "BUILDING_NUMBER",
        "SECONDARY_ADDRESS",
        "CITY",
        "STATE",
        "ZIP_CODE",
        "EMAIL",
        "PHONE",
        "CREDIT_CARD",
        "BANK_ACCOUNT",
        "ROUTING_NUMBER",
        "GOVERNMENT_ID",
        "PASSPORT",
        "DRIVERS_LICENSE",
        "TAX_ID",
        "SSN",
        "IMEI",
        "IP_ADDRESS",
    ];
    let mut out = 0.6_f64.to_be_bytes().to_vec();
    out.extend_from_slice(&(labels.len() as u32).to_be_bytes());
    for label in labels {
        push_string(&mut out, label)?;
    }
    Ok(out)
}
fn fingerprint(spans: &[Span]) -> String {
    let mut hash = 14_695_981_039_346_656_037_u64;
    let mut update = |bytes: &[u8]| {
        for byte in bytes {
            hash ^= *byte as u64;
            hash = hash.wrapping_mul(1_099_511_628_211);
        }
    };
    update(&(spans.len() as u32).to_be_bytes());
    for span in spans {
        update(&(span.label.len() as u32).to_be_bytes());
        update(span.label.as_bytes());
        update(&span.start.to_be_bytes());
        update(&span.end.to_be_bytes());
    }
    format!("{hash:016x}")
}
fn status_value(key: &str) -> Res<String> {
    let status =
        fs::read_to_string("/proc/self/status").map_err(|_| "process-status-unavailable")?;
    status
        .lines()
        .find_map(|line| line.strip_prefix(key).map(str::trim))
        .map(str::to_owned)
        .ok_or("process-status-field-missing")
}
fn rss(key: &str) -> Res<u64> {
    status_value(key)?
        .split_whitespace()
        .next()
        .ok_or("rss-field-missing")?
        .parse::<u64>()
        .map(|n| n * 1024)
        .map_err(|_| "rss-invalid")
}
fn json_string(text: &str) -> String {
    let mut out = String::from("\"");
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c < ' ' => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
fn stage_receipt(output: &Path, stage: u8) -> Res<()> {
    STAGE.store(stage, Ordering::Relaxed);
    let data = format!("{{\"status\":\"running\",\"stage\":{},\"license_verifier_calls\":{},\"license_verifier_successes\":{},\"disconnected_socket_count\":{},\"cases\":[]}}\n",
        json_string(STAGES[stage as usize]), LICENSE_CALLS.load(Ordering::Relaxed), LICENSE_VALID.load(Ordering::Relaxed), DISCONNECTED_SOCKETS.load(Ordering::Relaxed));
    fs::write(output, data).map_err(|_| "stage-receipt-write-failed")
}
struct CaseResult {
    id: String,
    utf16: usize,
    bytes: usize,
    warmup_ms: Option<f64>,
    samples: Vec<f64>,
    fingerprint: String,
    sample_fingerprints: Vec<String>,
    stable: bool,
    spans: Vec<Span>,
    current_rss: u64,
    peak_rss: u64,
}
impl CaseResult {
    fn json(&self) -> String {
        let spans = self
            .spans
            .iter()
            .map(|s| {
                format!(
                    "{{\"label\":{},\"start\":{},\"end\":{},\"confidence\":{}}}",
                    json_string(&s.label),
                    s.start,
                    s.end,
                    s.confidence
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        format!("{{\"id\":{},\"characters_utf16\":{},\"input_bytes\":{},\"warmup_ms\":{},\"milliseconds\":[{}],\"fingerprint\":{},\"sample_fingerprints\":[{}],\"stable\":{},\"spans\":[{}],\"current_rss_bytes\":{},\"peak_rss_bytes\":{}}}",
            json_string(&self.id),self.utf16,self.bytes,self.warmup_ms.map(|n|n.to_string()).unwrap_or("null".into()),self.samples.iter().map(f64::to_string).collect::<Vec<_>>().join(","),json_string(&self.fingerprint),self.sample_fingerprints.iter().map(|s|json_string(s)).collect::<Vec<_>>().join(","),self.stable,spans,self.current_rss,self.peak_rss)
    }
}
fn timed_classify(api: &Api, model: &Model, text: &str, options: &[u8]) -> Res<(f64, Vec<Span>)> {
    let start = Instant::now();
    let result = classify(api, model, text, options)?;
    Ok((start.elapsed().as_secs_f64() * 1000.0, result))
}
fn benchmark_case(
    api: &Api,
    model: &Model,
    input: Input,
    options: &[u8],
    repeats: usize,
) -> Res<CaseResult> {
    let (first_ms, spans) = timed_classify(api, model, &input.text, options)?;
    let base = fingerprint(&spans);
    let latency = input.id.starts_with("lat:");
    let mut samples = Vec::new();
    let mut fingerprints = Vec::new();
    if latency {
        for _ in 0..repeats {
            let (ms, actual) = timed_classify(api, model, &input.text, options)?;
            samples.push(ms);
            fingerprints.push(fingerprint(&actual));
        }
    } else {
        samples.push(first_ms);
        fingerprints.push(base.clone());
    }
    Ok(CaseResult {
        id: input.id,
        utf16: input.text.encode_utf16().count(),
        bytes: input.text.len(),
        warmup_ms: if latency { Some(first_ms) } else { None },
        samples,
        stable: fingerprints.iter().all(|f| f == &base),
        fingerprint: base,
        sample_fingerprints: fingerprints,
        spans,
        current_rss: rss("VmRSS:")?,
        peak_rss: rss("VmHWM:")?,
    })
}
struct RunMeta {
    proof: NativeProof,
    before_rss: u64,
    loaded_rss: u64,
    preflight_ms: f64,
    create_ms: f64,
    prepare_ms: f64,
    flush_ms: f64,
    threads: String,
    affinity: String,
    configured_threads: Option<String>,
    network: Option<NetworkProof>,
}
fn save(output: &Path, state: &str, meta: &RunMeta, cases: &[CaseResult]) -> Res<()> {
    let values = cases
        .iter()
        .map(CaseResult::json)
        .collect::<Vec<_>>()
        .join(",");
    let network = meta.network.as_ref().ok_or("network-proof-missing")?;
    let states = network
        .disconnected
        .iter()
        .map(|p| p.tcp_state.to_string())
        .collect::<Vec<_>>()
        .join(",");
    let offline = format!("{{\"mode\":\"simulated disconnect then libseccomp TSYNC EPERM\",\"licensing_flushed_before_disconnect\":true,\"disconnected_socket_count\":{},\"retained_disconnected_internet_descriptors\":{},\"existing_active_internet_sockets\":0,\"tcp_states_after_shutdown\":[{}],\"shutdown_read_and_write_checks\":true,\"sdk_descriptors_not_closed\":true,\"socket_self_test\":true,\"input_read_after_seal\":true}}",network.disconnected.len(),network.retained_descriptors,states);
    let data = format!("{{\"status\":{},\"backend\":\"Redact 4.1.0 C ABI called directly from Rust\",\"label_policy\":\"browser20 threshold0.6\",\"offset_units\":\"UTF16 half-open\",\"fingerprint_algorithm\":\"FNV1a64 BE-count + BE-label-length,label,BE-start,BE-end; confidence excluded\",\"native_preflight_ms\":{},\"create_ms\":{},\"model_load_ms\":{},\"license_flush_ms\":{},\"license_verifier_calls\":{},\"license_verifier_successes\":{},\"threads_after_model_load\":{},\"cpu_affinity\":{},\"dal_litert_threads\":{},\"before_native_load_rss_bytes\":{},\"after_model_load_rss_bytes\":{},\"current_rss_bytes\":{},\"peak_rss_bytes\":{},\"brotli\":{{\"version\":\"1.1.1\",\"version_address\":\"0x{:x}\",\"decoder_address\":\"0x{:x}\",\"library\":{}}},\"offline\":{},\"cases\":[{}]}}\n",
        json_string(state),meta.preflight_ms,meta.create_ms,meta.prepare_ms,meta.flush_ms,LICENSE_CALLS.load(Ordering::Relaxed),LICENSE_VALID.load(Ordering::Relaxed),json_string(&meta.threads),json_string(&meta.affinity),meta.configured_threads.as_ref().map(|s|json_string(s)).unwrap_or("null".into()),meta.before_rss,meta.loaded_rss,rss("VmRSS:")?,rss("VmHWM:")?,meta.proof.version_address,meta.proof.decoder_address,json_string(&meta.proof.decoder_path),offline,values);
    let temp = output.with_extension(format!("json.{}.tmp", std::process::id()));
    fs::write(&temp, data).map_err(|_| "receipt-write-failed")?;
    fs::rename(temp, output).map_err(|_| "receipt-rename-failed")?;
    CASE_RECEIPT_SAVED.store(true, Ordering::Relaxed);
    Ok(())
}
fn run(args: &[String]) -> Res<()> {
    if args.len() != 6 {
        return Err("usage-native-model-input-output-repeats");
    }
    let repeats: usize = args[5].parse().map_err(|_| "invalid-repetitions")?;
    if !(1..=15).contains(&repeats) {
        return Err("repetitions-out-of-bounds");
    }
    let output = Path::new(&args[4]);
    if output.exists() {
        return Err("fresh-output-required");
    }
    if let Some(parent) = output.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|_| "receipt-directory-failed")?;
        }
    }
    let mut initial = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)
        .map_err(|_| "fresh-output-required")?;
    initial
        .write_all(b"{\"status\":\"running\",\"stage\":\"arguments\",\"cases\":[]}\n")
        .map_err(|_| "stage-receipt-write-failed")?;
    OUTPUT_OWNED.store(true, Ordering::Relaxed);
    drop(initial);
    let configured_threads = std::env::var("DAL_LITERT_THREADS").ok();
    if let Some(value) = &configured_threads {
        let n = value
            .parse::<u32>()
            .map_err(|_| "invalid-native-thread-setting")?;
        if n == 0 || n > 64 {
            return Err("native-thread-setting-out-of-bounds");
        }
    }
    for (name, size) in [
        ("redact.tflite", 24_529_472),
        ("redact_tokenizer.bin", 391_416),
        ("labels.json", 3_842),
    ] {
        if fs::metadata(Path::new(&args[2]).join(name))
            .map_err(|_| "prepopulated-model-required")?
            .len()
            != size
        {
            return Err("unexpected-model-file-size");
        }
    }
    let before_rss = rss("VmRSS:")?;
    stage_receipt(output, 1)?;
    let start = Instant::now();
    let (api, proof) = native_api(Path::new(&args[1]))?;
    let preflight_ms = start.elapsed().as_secs_f64() * 1000.0;
    stage_receipt(output, 2)?;
    let id = CString::new("redact").map_err(|_| "model-id")?;
    let directory = CString::new(args[2].as_bytes()).map_err(|_| "model-path-nul")?;
    let start = Instant::now();
    let pointer = unsafe { (api.create)(id.as_ptr(), std::ptr::null(), directory.as_ptr()) };
    if pointer.is_null() {
        return Err("sdk-create-failed");
    }
    let model = Model {
        pointer,
        destroy: api.destroy,
    };
    let create_ms = start.elapsed().as_secs_f64() * 1000.0;
    stage_receipt(output, 3)?;
    let start = Instant::now();
    if unsafe { (api.download)(model.pointer) } != 0 {
        return Err("sdk-download-or-prepare-failed");
    }
    let prepare_ms = start.elapsed().as_secs_f64() * 1000.0;
    stage_receipt(output, 4)?;
    let start = Instant::now();
    unsafe { (api.flush)() };
    let flush_ms = start.elapsed().as_secs_f64() * 1000.0;
    let mut meta = RunMeta {
        proof,
        before_rss,
        loaded_rss: rss("VmRSS:")?,
        preflight_ms,
        create_ms,
        prepare_ms,
        flush_ms,
        threads: status_value("Threads:")?,
        affinity: status_value("Cpus_allowed_list:")?,
        configured_threads,
        network: None,
    };
    stage_receipt(output, 5)?;
    meta.network = Some(seal_network()?);
    stage_receipt(output, 6)?;
    if fs::metadata(&args[3])
        .map_err(|_| "input-file-unavailable")?
        .len()
        > MAX_INPUT as u64
    {
        return Err("input-file-limit");
    }
    let bytes = fs::read(&args[3]).map_err(|_| "input-read-failed")?;
    let inputs = parse_inputs(&bytes)?;
    let options = options()?;
    let mut results = Vec::new();
    save(output, "running", &meta, &results)?;
    for input in inputs {
        STAGE.store(7, Ordering::Relaxed);
        match benchmark_case(&api, &model, input, &options, repeats) {
            Ok(result) => {
                let stable = result.stable;
                results.push(result);
                STAGE.store(8, Ordering::Relaxed);
                save(
                    output,
                    if stable { "running" } else { "failed" },
                    &meta,
                    &results,
                )?;
                if !stable {
                    return Err("result-fingerprint-drift");
                }
            }
            Err(error) => {
                save(output, "failed", &meta, &results)?;
                return Err(error);
            }
        }
    }
    STAGE.store(8, Ordering::Relaxed);
    save(output, "complete", &meta, &results)?;
    drop(model);
    Ok(())
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    match std::panic::catch_unwind(|| run(&args)).unwrap_or(Err("rust-panic")) {
        Ok(()) => println!("redact-rust: complete"),
        Err(error) => {
            let stage = STAGES[STAGE.load(Ordering::Relaxed) as usize];
            if args.len() == 6
                && CASE_RECEIPT_SAVED.load(Ordering::Relaxed)
                && OUTPUT_OWNED.load(Ordering::Relaxed)
            {
                if let Ok(mut current) = fs::read_to_string(&args[4]) {
                    current =
                        current.replacen("\"status\":\"running\"", "\"status\":\"failed\"", 1);
                    if let Some(end) = current.rfind('}') {
                        current.insert_str(
                            end,
                            &format!(
                                ",\"stage\":{},\"error_type\":{}",
                                json_string(stage),
                                json_string(error)
                            ),
                        );
                        let _ = fs::write(&args[4], current);
                    }
                }
            }
            if args.len() == 6
                && !CASE_RECEIPT_SAVED.load(Ordering::Relaxed)
                && (OUTPUT_OWNED.load(Ordering::Relaxed) || !Path::new(&args[4]).exists())
            {
                let _=fs::write(&args[4],format!("{{\"status\":\"failed\",\"stage\":{},\"error_type\":{},\"license_verifier_calls\":{},\"license_verifier_successes\":{},\"disconnected_socket_count\":{}}}\n",json_string(stage),json_string(error),LICENSE_CALLS.load(Ordering::Relaxed),LICENSE_VALID.load(Ordering::Relaxed),DISCONNECTED_SOCKETS.load(Ordering::Relaxed)));
            }
            println!("redact-rust: failed:{stage}:{error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    // contract-test-file: tooling
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::os::fd::AsRawFd;
    #[test]
    fn simulated_disconnect_preserves_descriptor_and_blocks_io() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (_peer, _) = listener.accept().unwrap();
        let fd = client.as_raw_fd();
        let before = fs::read_link(format!("/proc/self/fd/{fd}")).unwrap();
        let inode = before
            .to_string_lossy()
            .strip_prefix("socket:[")
            .unwrap()
            .strip_suffix(']')
            .unwrap()
            .to_owned();
        let socket = InternetSocket {
            fd,
            inode,
            tcp: true,
        };
        assert!(verify_disconnected_socket(&socket, false).is_err());
        let proof = shutdown_licensing_socket(&socket).unwrap();
        assert!([4u8, 5, 6, 7, 9, 11].contains(&proof.tcp_state));
        assert_eq!(
            fs::read_link(format!("/proc/self/fd/{fd}")).unwrap(),
            before
        );
        let mut socket_type = 0i32;
        let mut length = std::mem::size_of::<i32>() as u32;
        assert_eq!(
            unsafe { getsockopt(fd, 1, 3, (&mut socket_type as *mut i32).cast(), &mut length) },
            0
        );
        assert_eq!(socket_type, 1); // still the original open SOCK_STREAM descriptor
        assert!(client.write(b"not transmitted").is_err());
        let mut byte = [0u8; 1];
        assert_eq!(client.read(&mut byte).unwrap(), 0);
        verify_disconnected_socket(&socket, false).unwrap();
    }
    #[test]
    fn bounded_codec_and_ids() {
        let mut bytes = 1u32.to_be_bytes().to_vec();
        push_string(&mut bytes, "q:unicode").unwrap();
        push_string(&mut bytes, "👋 Amina").unwrap();
        let parsed = parse_inputs(&bytes).unwrap();
        assert_eq!(parsed[0].text, "👋 Amina");
        assert_eq!(parsed[0].id, "q:unicode");
        assert!(parse_inputs(&bytes[..bytes.len() - 1]).is_err());
        bytes.extend([0]);
        assert!(parse_inputs(&bytes).is_err());
        let mut cursor = Cursor::new(&[0xff, 0xff, 0xff, 0xff]);
        assert!(cursor.string(128).is_err());
    }
    #[test]
    fn exact_unicode_originals() {
        let units: Vec<u16> = "👋 Amina".encode_utf16().collect();
        assert!(validate_original(&units, 3, 8, "Amina").is_ok());
        assert!(validate_original(&units, 2, 7, "Amina").is_err());
        assert!(validate_original(&units, 0, 1, "�").is_err());
        assert!(validate_original(&units, 3, 9, "Amina").is_err());
    }
    fn result_payload(redacted: &str, items: &[(&str, &str, &str, u32, u32)]) -> Vec<u8> {
        let mut payload = Vec::new();
        push_string(&mut payload, redacted).unwrap();
        payload.extend_from_slice(&(items.len() as u32).to_be_bytes());
        for (label, original, placeholder, start, end) in items {
            push_string(&mut payload, label).unwrap();
            push_string(&mut payload, original).unwrap();
            push_string(&mut payload, placeholder).unwrap();
            payload.extend_from_slice(&0.9f64.to_be_bytes());
            payload.extend_from_slice(&start.to_be_bytes());
            payload.extend_from_slice(&end.to_be_bytes());
        }
        payload
    }
    #[test]
    fn rejects_valid_span_with_wrong_redacted_output() {
        let payload = result_payload(
            "👋 Amina",
            &[("GIVEN_NAME", "Amina", "[GIVEN_NAME_1]", 3, 8)],
        );
        assert_eq!(
            parse_result(&payload, "👋 Amina").unwrap_err(),
            "sdk-redacted-text-mismatch"
        );
        assert!(parse_result(&result_payload("changed", &[]), "unchanged").is_err());
    }
    #[test]
    fn rejects_wrong_or_ambiguous_placeholders_and_overlap() {
        let wrong_output_token = result_payload(
            "👋 [EMAIL_1]",
            &[("GIVEN_NAME", "Amina", "[GIVEN_NAME_1]", 3, 8)],
        );
        assert!(parse_result(&wrong_output_token, "👋 Amina").is_err());
        let wrong_mapping = result_payload(
            "👋 [EMAIL_1]",
            &[("GIVEN_NAME", "Amina", "[EMAIL_1]", 3, 8)],
        );
        assert_eq!(
            parse_result(&wrong_mapping, "👋 Amina").unwrap_err(),
            "invalid-sdk-placeholder"
        );
        let collision = result_payload(
            "[GIVEN_NAME_1] [GIVEN_NAME_1]",
            &[("GIVEN_NAME", "Amina", "[GIVEN_NAME_1]", 0, 5)],
        );
        assert_eq!(
            parse_result(&collision, "Amina [GIVEN_NAME_1]").unwrap_err(),
            "ambiguous-placeholder-mapping"
        );
        let overlapping = result_payload(
            "unused",
            &[
                ("GIVEN_NAME", "Amina", "[GIVEN_NAME_1]", 0, 5),
                ("SURNAME", "mina", "[SURNAME_1]", 1, 5),
            ],
        );
        assert_eq!(
            parse_result(&overlapping, "Amina").unwrap_err(),
            "invalid-result-order-or-confidence"
        );
    }
    #[test]
    fn exact_unicode_sdk_redaction_and_restore_roundtrip() {
        for original in ["Élodie", "E\u{301}lodie"] {
            let text = format!("👋 {original}\r\n");
            let end = 3 + original.encode_utf16().count() as u32;
            let payload = result_payload(
                "👋 [GIVEN_NAME_1]\r\n",
                &[("GIVEN_NAME", original, "[GIVEN_NAME_1]", 3, end)],
            );
            let spans = parse_result(&payload, &text).unwrap();
            assert_eq!(spans.len(), 1);
            assert_eq!((spans[0].start, spans[0].end), (3, end));
        }
        let payload = result_payload(
            "[GIVEN_NAME_1] [GIVEN_NAME_2]",
            &[
                ("GIVEN_NAME", "Amina", "[GIVEN_NAME_1]", 0, 5),
                ("GIVEN_NAME", "Binta", "[GIVEN_NAME_2]", 6, 11),
            ],
        );
        assert_eq!(parse_result(&payload, "Amina Binta").unwrap().len(), 2);
    }
    #[test]
    fn fingerprint_excludes_confidence() {
        let a = Span {
            label: "GIVEN_NAME".into(),
            start: 3,
            end: 8,
            confidence: 0.6,
        };
        let mut b = a.clone();
        b.confidence = 0.9;
        assert_eq!(fingerprint(&[a.clone()]), fingerprint(&[b.clone()]));
        b.end = 7;
        assert_ne!(fingerprint(&[a]), fingerprint(&[b]));
    }
    #[test]
    fn json_strings_escape_controls() {
        assert_eq!(json_string("q:a\"\\\n"), "\"q:a\\\"\\\\\\n\"");
        assert_eq!(json_string("\0\t"), "\"\\u0000\\t\"");
    }
    #[test]
    fn der_integer_padding() {
        let mut raw = [0u8; 64];
        raw[0] = 0x80;
        raw[63] = 1;
        let der = p1363_der(&raw).unwrap();
        assert_eq!(&der[..5], &[0x30, 38, 2, 33, 0]);
        assert_eq!(&der[der.len() - 3..], &[2, 1, 1]);
        assert!(p1363_der(&raw[..63]).is_err());
    }
    fn der_to_p1363(der: &[u8]) -> [u8; 64] {
        assert_eq!(der[0], 0x30);
        assert_eq!(der[1] as usize, der.len() - 2);
        let mut at = 2;
        let mut out = [0u8; 64];
        for slot in 0..2 {
            assert_eq!(der[at], 2);
            let len = der[at + 1] as usize;
            at += 2;
            let mut integer = &der[at..at + len];
            at += len;
            if integer.len() == 33 {
                assert_eq!(integer[0], 0);
                integer = &integer[1..];
            }
            assert!(integer.len() <= 32);
            let start = slot * 32 + 32 - integer.len();
            out[start..slot * 32 + 32].copy_from_slice(integer);
        }
        assert_eq!(at, der.len());
        out
    }
    #[test]
    fn real_openssl_es256_valid_and_tampered() {
        let ssl = openssl().unwrap();
        unsafe {
            let ctx_new: unsafe extern "C" fn(c_int, *mut c_void) -> *mut c_void =
                symbol(ssl._handle, "EVP_PKEY_CTX_new_id").unwrap();
            let keygen_init: unsafe extern "C" fn(*mut c_void) -> c_int =
                symbol(ssl._handle, "EVP_PKEY_keygen_init").unwrap();
            let curve: unsafe extern "C" fn(*mut c_void, c_int) -> c_int =
                symbol(ssl._handle, "EVP_PKEY_CTX_set_ec_paramgen_curve_nid").unwrap();
            let keygen: unsafe extern "C" fn(*mut c_void, *mut *mut c_void) -> c_int =
                symbol(ssl._handle, "EVP_PKEY_keygen").unwrap();
            let ctx_free: MdFree = symbol(ssl._handle, "EVP_PKEY_CTX_free").unwrap();
            let get_public: unsafe extern "C" fn(
                *mut c_void,
                *const c_char,
                *mut u8,
                usize,
                *mut usize,
            ) -> c_int = symbol(ssl._handle, "EVP_PKEY_get_octet_string_param").unwrap();
            let sign_init: VerifyInit = symbol(ssl._handle, "EVP_DigestSignInit").unwrap();
            let sign: unsafe extern "C" fn(
                *mut c_void,
                *mut u8,
                *mut usize,
                *const u8,
                usize,
            ) -> c_int = symbol(ssl._handle, "EVP_DigestSign").unwrap();
            let key_context = ctx_new(408, std::ptr::null_mut());
            assert!(!key_context.is_null());
            assert_eq!(keygen_init(key_context), 1);
            assert_eq!(curve(key_context, 415), 1);
            let mut key = std::ptr::null_mut();
            assert_eq!(keygen(key_context, &mut key), 1);
            ctx_free(key_context);
            let mut public = [0u8; 65];
            let mut public_len = 0;
            let param = CString::new("pub").unwrap();
            assert_eq!(
                get_public(
                    key,
                    param.as_ptr(),
                    public.as_mut_ptr(),
                    public.len(),
                    &mut public_len
                ),
                1
            );
            assert_eq!(public_len, 65);
            let message = b"public deterministic license verifier test";
            let context = (ssl.md_new)();
            assert!(!context.is_null());
            assert_eq!(
                sign_init(
                    context,
                    std::ptr::null_mut(),
                    (ssl.sha256)(),
                    std::ptr::null_mut(),
                    key
                ),
                1
            );
            let mut der = [0u8; 80];
            let mut length = der.len();
            assert_eq!(
                sign(
                    context,
                    der.as_mut_ptr(),
                    &mut length,
                    message.as_ptr(),
                    message.len()
                ),
                1
            );
            (ssl.md_free)(context);
            (ssl.key_free)(key);
            let raw = der_to_p1363(&der[..length]);
            assert!(verify_es256(&raw, message, &public));
            assert!(!verify_es256(&raw, b"tampered public message", &public));
            let mut modified = raw;
            modified[0] ^= 1;
            assert!(!verify_es256(&modified, message, &public));
            assert!(!verify_es256(&raw[..63], message, &public));
            assert_eq!(
                license_verifier(
                    raw.as_ptr(),
                    64,
                    message.as_ptr(),
                    message.len() as i32,
                    public.as_ptr(),
                    65
                ),
                1
            );
            assert_eq!(
                license_verifier(
                    std::ptr::null(),
                    64,
                    message.as_ptr(),
                    message.len() as i32,
                    public.as_ptr(),
                    65
                ),
                0
            );
        }
    }
}
