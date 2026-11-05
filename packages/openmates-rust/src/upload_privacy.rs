//! Local upload preparation for audio (npm `@repo/upload-privacy` audio path
//! and uploadService `getUploadMimeType`). Lossless, best-effort container
//! metadata removal: `None` means "upload the original bytes", exactly like
//! the TypeScript `undefined` result. Parsers are bounds-checked and never
//! panic; private file bytes never appear in any error.

const MAX_UPLOAD_BYTES: usize = 100 * 1024 * 1024;

/// npm uploadService `getUploadMimeType` (extension based, lowercase).
pub fn upload_mime_type(filename: &str) -> &'static str {
    match js_extname(filename).to_ascii_lowercase().as_str() {
        ".jpg" | ".jpeg" => "image/jpeg",
        ".png" => "image/png",
        ".webp" => "image/webp",
        ".gif" => "image/gif",
        ".heic" => "image/heic",
        ".heif" => "image/heif",
        ".bmp" => "image/bmp",
        ".tif" | ".tiff" => "image/tiff",
        ".svg" => "image/svg+xml",
        ".pdf" => "application/pdf",
        ".mp3" => "audio/mpeg",
        ".m4a" | ".mp4" => "audio/mp4",
        ".wav" => "audio/wav",
        ".webm" => "audio/webm",
        ".ogg" | ".oga" => "audio/ogg",
        ".aac" => "audio/aac",
        _ => "application/octet-stream",
    }
}

/// Node `path.extname` of a basename: "" for dotfiles and names without a dot.
pub fn js_extname(filename: &str) -> &str {
    match filename.rfind('.') {
        Some(index) if index > 0 => &filename[index..],
        _ => "",
    }
}

const EXTENSIONS: &[(&str, &str)] = &[
    ("image/jpeg", "jpg"),
    ("image/png", "png"),
    ("image/webp", "webp"),
    ("image/gif", "gif"),
    ("image/svg+xml", "svg"),
    ("image/bmp", "bmp"),
    ("image/tiff", "tiff"),
    ("image/heic", "heic"),
    ("image/heif", "heif"),
    ("application/pdf", "pdf"),
    ("audio/mpeg", "mp3"),
    ("audio/aac", "aac"),
    ("audio/wav", "wav"),
    ("audio/x-wav", "wav"),
    ("audio/mp4", "m4a"),
    ("audio/webm", "webm"),
    ("audio/ogg", "ogg"),
];

fn at(bytes: &[u8], offset: usize, value: &[u8]) -> bool {
    bytes.get(offset..offset + value.len()) == Some(value)
}

/// npm upload-privacy `detectMimeType` (magic bytes first, then extension).
pub fn detect_mime_type(bytes: &[u8], declared: &str, filename: &str) -> String {
    if at(bytes, 0, &[0xff, 0xd8]) {
        return "image/jpeg".into();
    }
    if at(bytes, 0, &[0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) {
        return "image/png".into();
    }
    if at(bytes, 0, b"RIFF") {
        if at(bytes, 8, b"WEBP") {
            return "image/webp".into();
        }
        if at(bytes, 8, b"WAVE") {
            return "audio/wav".into();
        }
    }
    if at(bytes, 0, b"GIF87a") || at(bytes, 0, b"GIF89a") {
        return "image/gif".into();
    }
    if at(bytes, 0, b"BM") {
        return "image/bmp".into();
    }
    if at(bytes, 0, &[0x49, 0x49, 0x2a, 0]) || at(bytes, 0, &[0x4d, 0x4d, 0, 0x2a]) {
        return "image/tiff".into();
    }
    if at(bytes, 0, b"%PDF-") {
        return "application/pdf".into();
    }
    if at(bytes, 0, b"OggS") {
        return "audio/ogg".into();
    }
    if at(bytes, 0, b"ID3") {
        return if declared == "audio/aac" {
            "audio/aac"
        } else {
            "audio/mpeg"
        }
        .into();
    }
    if at(bytes, 0, &[0x1a, 0x45, 0xdf, 0xa3]) {
        return "audio/webm".into();
    }
    if at(bytes, 4, b"ftyp") {
        let brand = bytes.get(8..12).unwrap_or_default();
        if [&b"heic"[..], b"heif", b"heix", b"mif1", b"msf1"].contains(&brand) {
            return "image/heic".into();
        }
        return "audio/mp4".into();
    }
    let extension = js_extname(filename)
        .strip_prefix('.')
        .filter(|ext| !ext.is_empty() && ext.bytes().all(|b| b.is_ascii_alphanumeric()))
        .map(str::to_ascii_lowercase);
    if declared.is_empty() || declared == "application/octet-stream" {
        if let Some(ext) = extension.as_deref() {
            if let Some((mime, _)) = EXTENSIONS.iter().find(|(_, value)| *value == ext) {
                return (*mime).into();
            }
            match ext {
                "jpeg" => return "image/jpeg".into(),
                "tif" => return "image/tiff".into(),
                "mp4" => return "audio/mp4".into(),
                "oga" => return "audio/ogg".into(),
                _ => {}
            }
        }
    }
    declared.into()
}

/// Prepared audio upload bytes (npm `prepareUpload` result for audio).
pub struct PreparedAudioUpload {
    pub bytes: Vec<u8>,
    pub mime_type: String,
    /// False when metadata could not be removed and the original is uploaded
    /// (npm prints "Could not remove embedded file metadata" in that case).
    pub sanitized: bool,
}

/// Outcome when detected content is not audio: the caller must not upload,
/// since only the audio sanitizers are native.
#[derive(Debug, PartialEq, Eq)]
pub struct NotAudioContent;

/// npm `prepareUpload(bytes, filename, getUploadMimeType(filename))` for an
/// audio file. Non-audio detected content is refused instead of uploading it
/// without the image/document sanitizers.
pub fn prepare_audio_upload(
    bytes: Vec<u8>,
    filename: &str,
) -> std::result::Result<PreparedAudioUpload, NotAudioContent> {
    let declared = upload_mime_type(filename);
    let mime_type = detect_mime_type(&bytes, declared, filename);
    if !mime_type.starts_with("audio/") {
        return Err(NotAudioContent);
    }
    match strip_audio_metadata(&bytes, &mime_type) {
        Some(cleaned)
            if !cleaned.is_empty()
                && !(cleaned.len() > MAX_UPLOAD_BYTES && cleaned.len() > bytes.len()) =>
        {
            Ok(PreparedAudioUpload {
                bytes: cleaned,
                mime_type,
                sanitized: true,
            })
        }
        _ => Ok(PreparedAudioUpload {
            bytes,
            mime_type,
            sanitized: false,
        }),
    }
}

/// npm `stripAudioMetadata`; `Some(bytes)` may equal the input when clean.
pub fn strip_audio_metadata(bytes: &[u8], mime_type: &str) -> Option<Vec<u8>> {
    let lower = mime_type.to_ascii_lowercase();
    let mime = lower.split(';').next().unwrap_or_default().trim();
    match mime {
        "audio/wav" | "audio/wave" | "audio/x-wav" => strip_wav(bytes),
        "audio/mpeg" | "audio/mp3" => strip_mp3_or_adts(bytes, false),
        "audio/aac" | "audio/aacp" => strip_mp3_or_adts(bytes, true),
        "audio/mp4" | "audio/x-m4a" | "audio/m4a" => strip_mp4(bytes),
        "audio/webm" | "audio/x-matroska" => strip_webm(bytes),
        "audio/ogg" | "application/ogg" | "audio/opus" => strip_ogg(bytes),
        _ => None,
    }
}

fn u32le(bytes: &[u8], offset: usize) -> Option<u32> {
    Some(u32::from_le_bytes(
        bytes.get(offset..offset + 4)?.try_into().ok()?,
    ))
}
fn u32be(bytes: &[u8], offset: usize) -> Option<u32> {
    Some(u32::from_be_bytes(
        bytes.get(offset..offset + 4)?.try_into().ok()?,
    ))
}

fn strip_wav(bytes: &[u8]) -> Option<Vec<u8>> {
    if bytes.len() < 44
        || !at(bytes, 0, b"RIFF")
        || !at(bytes, 8, b"WAVE")
        || u64::from(u32le(bytes, 4)?) != bytes.len() as u64 - 8
    {
        return None;
    }
    let mut chunks: Vec<&[u8]> = vec![];
    let (mut offset, mut has_format, mut has_data, mut changed) = (12usize, false, false, false);
    while offset < bytes.len() {
        if offset + 8 > bytes.len() {
            return None;
        }
        let length = u32le(bytes, offset + 4)? as usize;
        let end = offset.checked_add(8 + length + (length & 1))?;
        if end > bytes.len() {
            return None;
        }
        let id = &bytes[offset..offset + 4];
        if id == b"fmt " || id == b"data" || id == b"fact" {
            has_format |= id == b"fmt ";
            has_data |= id == b"data";
            chunks.push(&bytes[offset..end]);
        } else if id == b"LIST" && at(bytes, offset + 8, b"wavl") {
            // LIST/wavl can contain audio blocks and must not be dropped.
            return None;
        } else {
            changed = true;
        }
        offset = end;
    }
    if !has_format || !has_data {
        return None;
    }
    if !changed {
        return Some(bytes.to_vec());
    }
    let length = 12 + chunks.iter().map(|c| c.len()).sum::<usize>();
    let riff = u32::try_from(length - 8).ok()?;
    let mut output = Vec::with_capacity(length);
    output.extend_from_slice(&bytes[..12]);
    output[4..8].copy_from_slice(&riff.to_le_bytes());
    for chunk in chunks {
        output.extend_from_slice(chunk);
    }
    Some(output)
}

fn synchsafe(bytes: &[u8], offset: usize) -> Option<usize> {
    let raw = bytes.get(offset..offset + 4)?;
    if raw.iter().any(|value| value & 0x80 != 0) {
        return None;
    }
    Some(
        raw.iter()
            .fold(0usize, |acc, b| (acc << 7) | usize::from(*b)),
    )
}

fn strip_mp3_or_adts(bytes: &[u8], adts: bool) -> Option<Vec<u8>> {
    let (mut start, mut end) = (0usize, bytes.len());
    while at(bytes, start, b"ID3") {
        if start + 10 > end || !(2..=4).contains(&bytes[start + 3]) {
            return None;
        }
        let size = synchsafe(bytes, start + 6)?;
        let footer = if bytes[start + 5] & 0x10 != 0 { 10 } else { 0 };
        let next = start + 10 + size + footer;
        if next > end || (footer != 0 && !at(bytes, next - 10, b"3DI")) {
            return None;
        }
        start = next;
    }
    // Tags occur in either order at the tail. APE's size includes its footer; a
    // separate 32-byte header, when present, precedes that size.
    loop {
        let mut removed = false;
        if end - start >= 128 && at(bytes, end - 128, b"TAG") {
            end -= 128;
            removed = true;
        }
        if end - start >= 32 && at(bytes, end - 32, b"APETAGEX") {
            let size = u32le(bytes, end - 32 + 12)? as usize;
            if size < 32 || size > end - start {
                return None;
            }
            let mut tag_start = end - size;
            if tag_start >= start + 32 && at(bytes, tag_start - 32, b"APETAGEX") {
                tag_start -= 32;
            }
            end = tag_start;
            removed = true;
        }
        if !removed {
            break;
        }
    }
    if end - start < if adts { 7 } else { 4 }
        || bytes[start] != 0xff
        || bytes[start + 1] & 0xf0 != 0xf0
    {
        return None;
    }
    if adts {
        if bytes[start + 1] & 0x06 != 0 || bytes[start + 2] & 0x3c == 0x3c {
            return None;
        }
    } else if bytes[start + 1] & 0x08 != 0x08 || bytes[start + 1] & 0x06 == 0 {
        return None;
    }
    Some(bytes[start..end].to_vec())
}

const MP4_METADATA: &[&[u8; 4]] = &[
    b"udta", b"meta", b"uuid", b"ilst", b"keys", b"ID32", b"XMP_", b"\xa9nam", b"\xa9ART",
    b"\xa9alb", b"\xa9day", b"\xa9too", b"\xa9cmt", b"\xa9wrt",
];
const MP4_CONTAINERS: &[&[u8; 4]] = &[
    b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"mvex", b"moof", b"traf",
    b"mfra", b"tref", b"ipro", b"iprp", b"ipco", b"wave",
];

struct Mp4Walk<'a> {
    bytes: &'a [u8],
    output: Vec<u8>,
    changed: bool,
    saw_media: bool,
    count: usize,
}
impl Mp4Walk<'_> {
    fn walk(&mut self, start: usize, end: usize, depth: usize) -> bool {
        if depth > 16 {
            return false;
        }
        let mut position = start;
        while position < end {
            self.count += 1;
            if self.count > 100_000 || position + 8 > end {
                return false;
            }
            let Some(size32) = u32be(self.bytes, position) else {
                return false;
            };
            let kind: [u8; 4] = self.bytes[position + 4..position + 8]
                .try_into()
                .unwrap_or_default();
            let (mut header, mut size) = (8usize, size32 as u64);
            if size32 == 1 {
                if position + 16 > end {
                    return false;
                }
                let (Some(high), Some(low)) = (
                    u32be(self.bytes, position + 8),
                    u32be(self.bytes, position + 12),
                ) else {
                    return false;
                };
                size = (u64::from(high) << 32) | u64::from(low);
                header = 16;
            } else if size32 == 0 {
                size = (end - position) as u64;
            }
            if size < header as u64 || position as u64 + size > end as u64 {
                return false;
            }
            let size = size as usize;
            if &kind == b"mdat" {
                self.saw_media = true;
            }
            if MP4_METADATA.contains(&&kind) {
                self.output[position + 4..position + 8].copy_from_slice(b"free");
                self.output[position + header..position + size].fill(0);
                self.changed = true;
            } else if &kind == b"free" || &kind == b"skip" {
                if self.bytes[position + header..position + size]
                    .iter()
                    .any(|v| *v != 0)
                {
                    self.changed = true;
                }
                self.output[position + header..position + size].fill(0);
            } else if MP4_CONTAINERS.contains(&&kind)
                && !self.walk(position + header, position + size, depth + 1)
            {
                return false;
            }
            position += size;
        }
        position == end
    }
}

fn strip_mp4(bytes: &[u8]) -> Option<Vec<u8>> {
    if bytes.len() < 16 || !at(bytes, 4, b"ftyp") {
        return None;
    }
    let mut walk = Mp4Walk {
        bytes,
        output: bytes.to_vec(),
        changed: false,
        saw_media: false,
        count: 0,
    };
    if !walk.walk(0, bytes.len(), 0) || !walk.saw_media {
        return None;
    }
    Some(if walk.changed {
        walk.output
    } else {
        bytes.to_vec()
    })
}

const EBML_MASTERS: &[u64] = &[
    0x1a45dfa3, 0x18538067, 0x114d9b74, 0x1549a966, 0x1654ae6b, 0xae, 0xe0, 0xe1, 0x1f43b675, 0xa0,
    0x1c53bb6b, 0xbb, 0xb7, 0x1941a469, 0x61a7, 0x1043a770, 0x45b9, 0xb6, 0x80,
];
const EBML_METADATA: &[u64] = &[
    0x1254c367, 0x67c8, 0x5741, 0x4d80, 0x4461, 0x7ba9, 0x73a4, 0x7384, 0x3cb923, 0x3eb923,
    0x3c83ab, 0x3e83bb, 0x536e,
];
const SEGMENT: u64 = 0x18538067;
const MAX_SAFE: u64 = (1 << 53) - 1;

struct Vint {
    value: u64,
    length: usize,
    unknown: bool,
}
fn ebml_vint(bytes: &[u8], offset: usize, end: usize, is_size: bool) -> Option<Vint> {
    if offset >= end {
        return None;
    }
    let first = bytes[offset];
    let limit = if is_size { 8 } else { 4 };
    let (mut mask, mut length) = (0x80u16, 1usize);
    while length <= limit && u16::from(first) & mask == 0 {
        mask >>= 1;
        length += 1;
    }
    if length > limit || offset + length > end {
        return None;
    }
    let mut value = if is_size {
        u64::from(first) & (u64::from(mask) - 1)
    } else {
        u64::from(first)
    };
    let mut unknown = is_size && value == u64::from(mask) - 1;
    for i in 1..length {
        value = value
            .checked_mul(256)?
            .checked_add(u64::from(bytes[offset + i]))?;
        unknown = unknown && bytes[offset + i] == 255;
    }
    Some(Vint {
        value,
        length,
        unknown,
    })
}

fn write_void(output: &mut [u8], start: usize, length: usize) -> bool {
    for size_length in 1..=8usize {
        let Some(payload) = length.checked_sub(1 + size_length) else {
            continue;
        };
        let limit = (1u128 << (7 * size_length)) - 1;
        if payload as u128 >= limit {
            continue;
        }
        output[start] = 0xec;
        for i in 0..size_length {
            let shift = 8 * (size_length - 1 - i);
            output[start + 1 + i] = ((payload as u128 >> shift) & 255) as u8;
        }
        output[start + 1] |= 1 << (8 - size_length);
        output[start + 1 + size_length..start + length].fill(0);
        return true;
    }
    false
}

struct WebmWalk<'a> {
    bytes: &'a [u8],
    output: Vec<u8>,
    changed: bool,
    saw_segment: bool,
    count: usize,
    crc: Vec<(usize, usize)>,
}
impl WebmWalk<'_> {
    fn walk(&mut self, start: usize, end: usize, depth: usize) -> bool {
        if depth > 16 {
            return false;
        }
        let mut position = start;
        while position < end {
            self.count += 1;
            if self.count > 100_000 {
                return false;
            }
            let Some(id) = ebml_vint(self.bytes, position, end, false) else {
                return false;
            };
            let Some(size) = ebml_vint(self.bytes, position + id.length, end, true) else {
                return false;
            };
            let payload = position + id.length + size.length;
            if size.unknown && id.value != SEGMENT {
                return false;
            }
            let next = if size.unknown {
                end as u64
            } else {
                match (payload as u64).checked_add(size.value) {
                    Some(next) => next,
                    None => return false,
                }
            };
            if next > MAX_SAFE || next > end as u64 || next < payload as u64 {
                return false;
            }
            let next = next as usize;
            if id.value == SEGMENT {
                self.saw_segment = true;
            }
            if EBML_METADATA.contains(&id.value) {
                if !write_void(&mut self.output, position, next - position) {
                    return false;
                }
                self.changed = true;
            } else if id.value == 0xbf {
                if size.value != 4 {
                    return false;
                }
                self.crc.push((position, next - position));
            } else if id.value == 0xec {
                if self.bytes[payload..next].iter().any(|v| *v != 0) {
                    self.changed = true;
                }
                self.output[payload..next].fill(0);
            } else if EBML_MASTERS.contains(&id.value) && !self.walk(payload, next, depth + 1) {
                return false;
            }
            position = next;
        }
        position == end
    }
}

fn strip_webm(bytes: &[u8]) -> Option<Vec<u8>> {
    if !at(bytes, 0, &[0x1a, 0x45, 0xdf, 0xa3]) {
        return None;
    }
    let mut walk = WebmWalk {
        bytes,
        output: bytes.to_vec(),
        changed: false,
        saw_segment: false,
        count: 0,
        crc: vec![],
    };
    if !walk.walk(0, bytes.len(), 0) || !walk.saw_segment {
        return None;
    }
    if !walk.changed {
        return Some(bytes.to_vec());
    }
    // CRC-32 covers its parent element's bytes. Voiding all parsed CRC elements
    // avoids retaining a checksum that can no longer validate after redaction.
    for (start, length) in std::mem::take(&mut walk.crc) {
        if !write_void(&mut walk.output, start, length) {
            return None;
        }
    }
    Some(walk.output)
}

#[path = "upload_privacy_images.rs"]
pub mod images;
#[path = "upload_privacy_ogg.rs"]
mod ogg;
use ogg::strip_ogg;

#[cfg(test)]
#[path = "upload_privacy_tests.rs"]
mod tests;
