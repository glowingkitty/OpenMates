//! Native image metadata removal (npm `@repo/upload-privacy` images.ts) and
//! the CLI `prepareUpload` decision for any local upload. JPEG, PNG, WebP,
//! GIF and Windows V3 BMP are rewritten exactly like the TypeScript parsers;
//! audio reuses the existing container sanitizers. Types whose npm path needs
//! a non-native sanitizer (SVG/XML, PDF/Office documents, sharp conversion of
//! TIFF/HEIC/other BMP) are refused instead of uploading unsanitized bytes.
//! Parsers are bounds-checked, never panic, and never echo file bytes.
use super::{detect_mime_type, strip_audio_metadata};
use std::borrow::Cow;

const MAX_UPLOAD_BYTES: usize = 100 * 1024 * 1024;

/// A parser rejected the bytes (npm `throw` inside the sanitizer).
#[derive(Debug, PartialEq, Eq)]
pub struct Malformed;
type Parsed<T> = Result<T, Malformed>;

fn need(bytes: &[u8], offset: usize, length: usize) -> Parsed<()> {
    match offset.checked_add(length) {
        Some(end) if end <= bytes.len() => Ok(()),
        _ => Err(Malformed),
    }
}
fn be16(b: &[u8], p: usize) -> usize {
    ((b[p] as usize) << 8) | b[p + 1] as usize
}
fn le16(b: &[u8], p: usize) -> usize {
    b[p] as usize | ((b[p + 1] as usize) << 8)
}
fn be32(b: &[u8], p: usize) -> usize {
    u32::from_be_bytes([b[p], b[p + 1], b[p + 2], b[p + 3]]) as usize
}
fn le32(b: &[u8], p: usize) -> usize {
    u32::from_le_bytes([b[p], b[p + 1], b[p + 2], b[p + 3]]) as usize
}
fn concat(parts: &[Cow<'_, [u8]>]) -> Vec<u8> {
    let mut out = Vec::with_capacity(parts.iter().map(|p| p.len()).sum());
    for part in parts {
        out.extend_from_slice(part);
    }
    out
}

fn tiff_orientation(data: &[u8], t: usize) -> Parsed<Option<u16>> {
    need(data, t, 8)?;
    let little = &data[t..t + 2] == b"II";
    if !little && &data[t..t + 2] != b"MM" {
        return Ok(None);
    }
    let r16 = |p: usize| if little { le16(data, p) } else { be16(data, p) };
    let r32 = |p: usize| if little { le32(data, p) } else { be32(data, p) };
    if r16(t + 2) != 42 {
        return Ok(None);
    }
    let ifd = t.checked_add(r32(t + 4)).ok_or(Malformed)?;
    need(data, ifd, 2)?;
    let count = r16(ifd);
    need(data, ifd + 2, count * 12)?;
    for i in 0..count {
        let p = ifd + 2 + i * 12;
        if r16(p) == 0x0112 && r16(p + 2) == 3 && r32(p + 4) == 1 {
            let value = r16(p + 8);
            return Ok((1..=8).contains(&value).then_some(value as u16));
        }
    }
    Ok(None)
}

fn minimal_tiff_orientation(orientation: u16) -> [u8; 26] {
    [
        73,
        73,
        42,
        0,
        8,
        0,
        0,
        0,
        1,
        0,
        0x12,
        1,
        3,
        0,
        1,
        0,
        0,
        0,
        orientation as u8,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
}

fn jpeg(bytes: &[u8]) -> Parsed<Vec<u8>> {
    need(bytes, 0, 4)?;
    if bytes[0] != 0xff || bytes[1] != 0xd8 {
        return Err(Malformed);
    }
    let mut parts: Vec<Cow<'_, [u8]>> = vec![Cow::Borrowed(&bytes[..2])];
    let mut p = 2;
    let mut orientation = None;
    let mut saw_scan = false;
    while p < bytes.len() {
        if bytes[p] != 0xff {
            return Err(Malformed);
        }
        p += 1;
        while bytes.get(p) == Some(&0xff) {
            p += 1;
        }
        need(bytes, p, 1)?;
        let marker = bytes[p];
        p += 1;
        if marker == 0xd9 {
            if !saw_scan {
                return Err(Malformed);
            }
            if let Some(o) = orientation.filter(|o| *o != 1) {
                let mut segment = vec![0xff, 0xe1, 0, 34, b'E', b'x', b'i', b'f', 0, 0];
                segment.extend_from_slice(&minimal_tiff_orientation(o));
                parts.insert(1, Cow::Owned(segment));
            }
            parts.push(Cow::Borrowed(&[0xff, 0xd9]));
            return Ok(concat(&parts));
        }
        if marker == 0x00 || marker == 0xd8 || (0xd0..=0xd7).contains(&marker) {
            return Err(Malformed);
        }
        need(bytes, p, 2)?;
        let length = be16(bytes, p);
        if length < 2 {
            return Err(Malformed);
        }
        let start = p - 2;
        need(bytes, p, length)?;
        p += length;
        if marker == 0xe1
            && orientation.is_none()
            && length >= 8
            && &bytes[start + 4..start + 10] == b"Exif\0\0"
        {
            let segment = &bytes[start..p];
            if segment.len() >= 16 {
                // Malformed EXIF is discarded, exactly like the npm try/catch.
                if let Ok(Some(o)) = tiff_orientation(segment, 10) {
                    orientation = Some(o);
                }
            }
        }
        // All APP and COM segments can carry identifying text.
        if marker == 0xee && length == 14 && &bytes[start + 4..start + 9] == b"Adobe" {
            let transform = bytes[p - 1];
            if transform <= 2 {
                parts.push(Cow::Owned(vec![
                    255, 238, 0, 14, 65, 100, 111, 98, 101, 0, 100, 0, 0, 0, 0, transform,
                ]));
            }
        } else if !(0xe0..=0xef).contains(&marker) && marker != 0xfe {
            parts.push(Cow::Borrowed(&bytes[start..p]));
        }
        if marker == 0xda {
            saw_scan = true;
            let scan_start = p;
            while p < bytes.len() - 1 {
                if bytes[p] != 0xff {
                    p += 1;
                    continue;
                }
                let next = bytes[p + 1];
                if next == 0x00 || next == 0xff || (0xd0..=0xd7).contains(&next) {
                    p += 2;
                    continue;
                }
                break;
            }
            need(bytes, p, 2)?;
            parts.push(Cow::Borrowed(&bytes[scan_start..p]));
        }
    }
    Err(Malformed)
}

const PNG_SIGNATURE: [u8; 8] = [137, 80, 78, 71, 13, 10, 26, 10];
const PNG_ALLOWED: &[&[u8; 4]] = &[
    b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"sBIT", b"cICP",
    b"bKGD", b"acTL", b"fcTL", b"fdAT",
];
fn png_crc(data: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for byte in data {
        crc ^= *byte as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ if crc & 1 == 1 { 0xedb8_8320 } else { 0 };
        }
    }
    crc ^ 0xffff_ffff
}
fn png_chunk(kind: &[u8; 4], data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(12 + data.len());
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    out.extend_from_slice(kind);
    out.extend_from_slice(data);
    let crc = png_crc(&out[4..]);
    out.extend_from_slice(&crc.to_be_bytes());
    out
}
fn png(bytes: &[u8]) -> Parsed<Vec<u8>> {
    need(bytes, 0, 8)?;
    if bytes[..8] != PNG_SIGNATURE {
        return Err(Malformed);
    }
    let mut parts: Vec<Cow<'_, [u8]>> = vec![Cow::Borrowed(&bytes[..8])];
    let (mut p, mut ihdr, mut idat) = (8usize, false, false);
    let mut orientation = None;
    while p < bytes.len() {
        need(bytes, p, 12)?;
        let length = be32(bytes, p);
        let kind: [u8; 4] = [bytes[p + 4], bytes[p + 5], bytes[p + 6], bytes[p + 7]];
        need(bytes, p, 12usize.checked_add(length).ok_or(Malformed)?)?;
        if !kind.iter().all(u8::is_ascii_alphabetic) {
            return Err(Malformed);
        }
        if !ihdr && &kind != b"IHDR" {
            return Err(Malformed);
        }
        if &kind == b"IHDR" {
            if ihdr || length != 13 {
                return Err(Malformed);
            }
            ihdr = true;
        }
        if &kind == b"IDAT" {
            idat = true;
        }
        if &kind == b"IEND" && (length != 0 || !idat) {
            return Err(Malformed);
        }
        if &kind == b"eXIf" && orientation.is_none() {
            if let Ok(Some(o)) = tiff_orientation(&bytes[p + 8..p + 8 + length], 0) {
                orientation = Some(o);
            }
        }
        let allowed = PNG_ALLOWED.contains(&&kind);
        if !allowed && kind[0].is_ascii_uppercase() {
            return Err(Malformed);
        }
        if &kind == b"IEND" {
            if let Some(o) = orientation.filter(|o| *o != 1) {
                let at = parts.len().min(2);
                parts.insert(
                    at,
                    Cow::Owned(png_chunk(b"eXIf", &minimal_tiff_orientation(o))),
                );
            }
        }
        if allowed {
            parts.push(Cow::Borrowed(&bytes[p..p + 12 + length]));
        }
        p += 12 + length;
        if &kind == b"IEND" {
            return Ok(concat(&parts));
        }
    }
    Err(Malformed)
}

const WEBP_ALLOWED: &[&[u8; 4]] = &[b"VP8X", b"VP8 ", b"VP8L", b"ALPH", b"ANIM", b"ANMF"];
fn webp_chunk(kind: &[u8; 4], data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(8 + data.len() + (data.len() & 1));
    out.extend_from_slice(kind);
    out.extend_from_slice(&(data.len() as u32).to_le_bytes());
    out.extend_from_slice(data);
    if data.len() & 1 == 1 {
        out.push(0);
    }
    out
}
fn chunk_end(p: usize, size: usize) -> Parsed<usize> {
    p.checked_add(8)
        .and_then(|v| v.checked_add(size))
        .and_then(|v| v.checked_add(size & 1))
        .ok_or(Malformed)
}
fn webp_frame(data: &[u8]) -> Parsed<Vec<u8>> {
    need(data, 0, 16)?;
    let mut parts: Vec<Cow<'_, [u8]>> = vec![Cow::Borrowed(&data[..16])];
    let (mut p, mut image) = (16usize, false);
    while p < data.len() {
        need(data, p, 8)?;
        let kind = &data[p..p + 4];
        let end = chunk_end(p, le32(data, p + 4))?;
        need(data, p, end - p)?;
        if kind == b"ALPH" || kind == b"VP8 " || kind == b"VP8L" {
            parts.push(Cow::Borrowed(&data[p..end]));
        }
        if kind == b"VP8 " || kind == b"VP8L" {
            image = true;
        }
        p = end;
    }
    if !image {
        return Err(Malformed);
    }
    Ok(concat(&parts))
}
fn webp(bytes: &[u8]) -> Parsed<Vec<u8>> {
    need(bytes, 0, 12)?;
    if &bytes[..4] != b"RIFF" || &bytes[8..12] != b"WEBP" {
        return Err(Malformed);
    }
    let end = 8 + le32(bytes, 4);
    if end < 12 || end > bytes.len() {
        return Err(Malformed);
    }
    let mut parts: Vec<Cow<'_, [u8]>> = Vec::new();
    let (mut p, mut image) = (12usize, false);
    while p < end {
        need(bytes, p, 8)?;
        let kind: [u8; 4] = [bytes[p], bytes[p + 1], bytes[p + 2], bytes[p + 3]];
        let size = le32(bytes, p + 4);
        let chunk = chunk_end(p, size)?;
        if chunk > end {
            return Err(Malformed);
        }
        if WEBP_ALLOWED.contains(&&kind) {
            if &kind == b"VP8X" {
                if size != 10 {
                    return Err(Malformed);
                }
                let mut copy = bytes[p..chunk].to_vec();
                copy[8] &= !0x2c; // ICC, EXIF, XMP flags
                parts.push(Cow::Owned(copy));
            } else if &kind == b"ANMF" {
                parts.push(Cow::Owned(webp_chunk(
                    b"ANMF",
                    &webp_frame(&bytes[p + 8..p + 8 + size])?,
                )));
            } else {
                parts.push(Cow::Borrowed(&bytes[p..chunk]));
            }
            if &kind == b"VP8 " || &kind == b"VP8L" || &kind == b"ANMF" {
                image = true;
            }
        }
        p = chunk;
    }
    if !image {
        return Err(Malformed);
    }
    let payload = concat(&parts);
    let mut out = Vec::with_capacity(12 + payload.len());
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&((payload.len() + 4) as u32).to_le_bytes());
    out.extend_from_slice(b"WEBP");
    out.extend_from_slice(&payload);
    Ok(out)
}

fn color_table(flags: u8) -> usize {
    if flags & 0x80 != 0 {
        3 * (1 << ((flags & 7) + 1))
    } else {
        0
    }
}
fn gif_blocks(bytes: &[u8], p: &mut usize) -> Parsed<()> {
    loop {
        need(bytes, *p, 1)?;
        let n = bytes[*p] as usize;
        *p += 1;
        need(bytes, *p, n)?;
        *p += n;
        if n == 0 {
            return Ok(());
        }
    }
}
fn gif(bytes: &[u8]) -> Parsed<Vec<u8>> {
    need(bytes, 0, 13)?;
    if &bytes[..6] != b"GIF87a" && &bytes[..6] != b"GIF89a" {
        return Err(Malformed);
    }
    let mut p = 13;
    let global = color_table(bytes[10]);
    need(bytes, p, global)?;
    p += global;
    let mut parts: Vec<Cow<'_, [u8]>> = vec![Cow::Borrowed(&bytes[..p])];
    let mut image = false;
    while p < bytes.len() {
        let start = p;
        let kind = bytes[p];
        p += 1;
        if kind == 0x3b {
            if !image {
                return Err(Malformed);
            }
            parts.push(Cow::Borrowed(&[0x3b]));
            return Ok(concat(&parts));
        }
        if kind == 0x2c {
            image = true;
            need(bytes, p, 9)?;
            let local = color_table(bytes[p + 8]);
            p += 9;
            need(bytes, p, local + 1)?;
            p += local + 1;
            gif_blocks(bytes, &mut p)?;
            parts.push(Cow::Borrowed(&bytes[start..p]));
            continue;
        }
        if kind != 0x21 {
            return Err(Malformed);
        }
        need(bytes, p, 1)?;
        let label = bytes[p];
        p += 1;
        if label == 0xf9 {
            need(bytes, p, 6)?;
            if bytes[p] != 4 || bytes[p + 5] != 0 {
                return Err(Malformed);
            }
            p += 6;
            parts.push(Cow::Borrowed(&bytes[start..p]));
        } else if label == 0xff || label == 0x01 {
            need(bytes, p, 1)?;
            let n = bytes[p] as usize;
            p += 1;
            need(bytes, p, n)?;
            let app = if label == 0xff {
                &bytes[p..p + n]
            } else {
                &[][..]
            };
            p += n;
            gif_blocks(bytes, &mut p)?;
            // NETSCAPE/ANIMEXTS carries loop count; plain text is visible content.
            if label == 0x01 || app == b"NETSCAPE2.0" || app == b"ANIMEXTS1.0" {
                parts.push(Cow::Borrowed(&bytes[start..p]));
            }
        } else {
            gif_blocks(bytes, &mut p)?;
        }
    }
    Err(Malformed)
}

/// `Ok(None)` is npm's `undefined`: a BMP variant only a decoder can rebuild.
fn bmp(bytes: &[u8]) -> Parsed<Option<Vec<u8>>> {
    need(bytes, 0, 54)?;
    if &bytes[..2] != b"BM" {
        return Err(Malformed);
    }
    if le32(bytes, 14) != 40 || le16(bytes, 26) != 1 || le32(bytes, 30) != 0 {
        return Ok(None);
    }
    let bpp = le16(bytes, 28) as u64;
    let width = i32::from_le_bytes([bytes[18], bytes[19], bytes[20], bytes[21]]) as i64;
    let height = i32::from_le_bytes([bytes[22], bytes[23], bytes[24], bytes[25]]) as i64;
    if !(bpp == 24 || bpp == 32) || width <= 0 || height == 0 || le32(bytes, 46) != 0 {
        return Ok(None);
    }
    let row = (width as u64 * bpp).div_ceil(32) * 4;
    let pixel_bytes = row * height.unsigned_abs();
    let offset = le32(bytes, 10);
    if pixel_bytes >= (1u64 << 53) || offset < 54 {
        return Err(Malformed);
    }
    let pixel_bytes = usize::try_from(pixel_bytes).map_err(|_| Malformed)?;
    need(bytes, offset, pixel_bytes)?;
    let total = 54 + pixel_bytes;
    let total32 = u32::try_from(total).map_err(|_| Malformed)?;
    let mut out = Vec::with_capacity(total);
    out.extend_from_slice(&bytes[..54]);
    out[2..6].copy_from_slice(&total32.to_le_bytes());
    out[10..14].copy_from_slice(&54u32.to_le_bytes());
    out[34..38].copy_from_slice(&(pixel_bytes as u32).to_le_bytes());
    out[6..10].fill(0);
    out[38..54].fill(0); // resolution and palette fields can identify devices
    out.extend_from_slice(&bytes[offset..offset + pixel_bytes]);
    Ok(Some(out))
}

/// npm `stripImageMetadata` outcome for one detected base type.
#[derive(Debug, PartialEq, Eq)]
pub enum ImageStrip {
    /// Not an image type the npm image parser handles.
    NotImage,
    /// npm handles this type with a sanitizer that is not native (SVG).
    NotNative,
    Stripped(Parsed<Option<Vec<u8>>>),
}
pub fn strip_image_metadata(bytes: &[u8], mime_type: &str) -> ImageStrip {
    let lower = mime_type.to_ascii_lowercase();
    match lower.split(';').next().unwrap_or_default().trim() {
        "image/jpeg" | "image/jpg" => ImageStrip::Stripped(jpeg(bytes).map(Some)),
        "image/png" => ImageStrip::Stripped(png(bytes).map(Some)),
        "image/webp" => ImageStrip::Stripped(webp(bytes).map(Some)),
        "image/gif" => ImageStrip::Stripped(gif(bytes).map(Some)),
        "image/bmp" => ImageStrip::Stripped(bmp(bytes)),
        "image/svg+xml" => ImageStrip::NotNative,
        _ => ImageStrip::NotImage,
    }
}

/// npm uploadService `prepareUpload` result.
#[derive(Debug)]
pub struct PreparedUpload {
    pub bytes: Vec<u8>,
    pub mime_type: String,
    /// False means npm's "Could not remove embedded file metadata" warning.
    pub sanitized: bool,
}
/// The npm path for this type needs a sanitizer or converter that is not
/// native; the caller must not upload the original bytes.
#[derive(Debug, PartialEq, Eq)]
pub struct NativeSanitizerUnavailable {
    pub mime_type: String,
}

fn document_like(mime: &str, filename: &str) -> bool {
    let ext = filename
        .rsplit('.')
        .next()
        .unwrap_or_default()
        .to_ascii_lowercase();
    ext == "pdf"
        || mime == "application/pdf"
        || ["docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "zip"].contains(&ext.as_str())
        || matches!(
            mime,
            "application/epub+zip" | "application/zip" | "application/x-zip-compressed"
        )
        || mime.starts_with("application/vnd.openxmlformats-officedocument.")
        || mime.starts_with("application/vnd.oasis.opendocument.")
}

/// npm `prepareUpload(bytes, filename, declaredMime)` (sanitizeUploadBytes
/// plus the CLI fallback), restricted to native sanitizers.
pub fn prepare_upload(
    bytes: Vec<u8>,
    filename: &str,
    declared_mime: &str,
) -> Result<PreparedUpload, NativeSanitizerUnavailable> {
    let declared = declared_mime
        .split(';')
        .next()
        .unwrap_or_default()
        .to_ascii_lowercase();
    let base = detect_mime_type(&bytes, &declared, filename);
    let mime_type = if base.is_empty() {
        declared_mime.to_owned()
    } else {
        base.clone()
    };
    let unavailable = || NativeSanitizerUnavailable {
        mime_type: mime_type.clone(),
    };
    let cleaned: Result<Option<Vec<u8>>, Malformed> = match strip_image_metadata(&bytes, &base) {
        ImageStrip::NotNative => return Err(unavailable()),
        ImageStrip::Stripped(result) => result,
        ImageStrip::NotImage => match strip_audio_metadata(&bytes, &base) {
            Some(cleaned) => Ok(Some(cleaned)),
            None if document_like(&base, filename) => return Err(unavailable()),
            None => Ok(None),
        },
    };
    let accepted = match cleaned {
        Ok(Some(cleaned))
            if !cleaned.is_empty()
                && !(cleaned.len() > MAX_UPLOAD_BYTES && cleaned.len() > bytes.len()) =>
        {
            Some(cleaned)
        }
        // npm `failed` (parser threw, empty or oversized rewrite).
        Ok(Some(_)) | Err(Malformed) => None,
        // npm `unsupported`: these four are converted with sharp in npm.
        Ok(None)
            if matches!(
                mime_type.as_str(),
                "image/tiff" | "image/heic" | "image/heif" | "image/bmp"
            ) =>
        {
            return Err(unavailable());
        }
        Ok(None) => None,
    };
    Ok(match accepted {
        Some(cleaned) => PreparedUpload {
            bytes: cleaned,
            mime_type,
            sanitized: true,
        },
        None => PreparedUpload {
            bytes,
            mime_type,
            sanitized: false,
        },
    })
}

#[cfg(test)]
#[path = "upload_privacy_images_tests.rs"]
mod tests;
