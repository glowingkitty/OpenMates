use super::*;

fn exif_orientation(orientation: u8) -> Vec<u8> {
    let mut tiff = vec![
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
        orientation,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ];
    tiff.extend_from_slice(b"GPS-SECRET");
    tiff
}
fn jpeg_fixture() -> Vec<u8> {
    let mut b = vec![0xff, 0xd8];
    let mut app1 = b"Exif\0\0".to_vec();
    app1.extend(exif_orientation(6));
    b.extend([0xff, 0xe1]);
    b.extend(((app1.len() + 2) as u16).to_be_bytes());
    b.extend(app1);
    b.extend([0xff, 0xfe, 0, 8]);
    b.extend(b"secret");
    b.extend([0xff, 0xdb, 0, 4, 1, 2]);
    b.extend([0xff, 0xda, 0, 4, 3, 4, 9, 9, 0xff, 0x00, 7]);
    b.extend([0xff, 0xd9]);
    b
}

#[test]
fn jpeg_drops_app_and_comment_segments_and_keeps_orientation_only() {
    let out = jpeg(&jpeg_fixture()).unwrap();
    assert!(!out.windows(6).any(|w| w == b"secret"));
    assert!(!out.windows(10).any(|w| w == b"GPS-SECRET"));
    let mut expected = vec![0xff, 0xd8, 0xff, 0xe1, 0, 34, b'E', b'x', b'i', b'f', 0, 0];
    expected.extend(minimal_tiff_orientation(6));
    expected.extend([
        0xff, 0xdb, 0, 4, 1, 2, 0xff, 0xda, 0, 4, 3, 4, 9, 9, 0xff, 0x00, 7, 0xff, 0xd9,
    ]);
    assert_eq!(out, expected);
    assert_eq!(jpeg(&[0xff, 0xd8, 0xff, 0xd9]), Err(Malformed));
    assert_eq!(jpeg(&[0xff, 0xd8, 0xff, 0xdb, 0, 40]), Err(Malformed));
}

fn png_fixture() -> Vec<u8> {
    let mut b = PNG_SIGNATURE.to_vec();
    b.extend(png_chunk(b"IHDR", &[0; 13]));
    b.extend(png_chunk(b"tEXt", b"Author\0secret"));
    b.extend(png_chunk(b"eXIf", &exif_orientation(3)));
    b.extend(png_chunk(b"IDAT", &[1, 2, 3]));
    b.extend(png_chunk(b"IEND", &[]));
    b
}

#[test]
fn png_keeps_allowed_chunks_with_valid_crc() {
    let out = png(&png_fixture()).unwrap();
    let mut expected = PNG_SIGNATURE.to_vec();
    expected.extend(png_chunk(b"IHDR", &[0; 13]));
    expected.extend(png_chunk(b"eXIf", &minimal_tiff_orientation(3)));
    expected.extend(png_chunk(b"IDAT", &[1, 2, 3]));
    expected.extend(png_chunk(b"IEND", &[]));
    assert_eq!(out, expected);
    // Known CRC of an empty IEND chunk.
    assert_eq!(png_crc(b"IEND"), 0xae42_6082);
    let mut critical = PNG_SIGNATURE.to_vec();
    critical.extend(png_chunk(b"IHDR", &[0; 13]));
    critical.extend(png_chunk(b"ZZZZ", &[]));
    assert_eq!(png(&critical), Err(Malformed));
}

#[test]
fn webp_clears_metadata_flags_and_drops_exif() {
    let mut payload = Vec::new();
    payload.extend(webp_chunk(
        b"VP8X",
        &[0x2c | 0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ));
    payload.extend(webp_chunk(b"EXIF", b"secret"));
    payload.extend(webp_chunk(b"VP8L", &[1, 2, 3]));
    let mut b = b"RIFF".to_vec();
    b.extend(((payload.len() + 4) as u32).to_le_bytes());
    b.extend(b"WEBP");
    b.extend(&payload);
    let out = webp(&b).unwrap();
    assert!(!out.windows(6).any(|w| w == b"secret"));
    assert_eq!(out[20], 0x10);
    assert_eq!(le32(&out, 4), out.len() - 8);
}

#[test]
fn gif_drops_comment_extensions() {
    let mut b = b"GIF89a".to_vec();
    b.extend([1, 0, 1, 0, 0, 0, 0]);
    b.extend([0x21, 0xfe, 6]);
    b.extend(b"secret");
    b.push(0);
    b.extend([0x2c, 0, 0, 0, 0, 1, 0, 1, 0, 0, 2, 1, 5, 0]);
    b.push(0x3b);
    let out = gif(&b).unwrap();
    assert!(!out.windows(6).any(|w| w == b"secret"));
    assert_eq!(out.last(), Some(&0x3b));
}

#[test]
fn bmp_rebuilds_v3_and_defers_other_variants() {
    let mut b = vec![0u8; 54];
    b[..2].copy_from_slice(b"BM");
    b[10] = 54;
    b[14] = 40;
    b[18] = 1;
    b[22] = 1;
    b[26] = 1;
    b[28] = 24;
    b[38] = 0x55;
    b.extend([1, 2, 3, 0]);
    b.extend(b"trailer");
    let out = bmp(&b).unwrap().unwrap();
    assert_eq!(out.len(), 58);
    assert_eq!(out[38], 0);
    b[14] = 124;
    assert_eq!(bmp(&b), Ok(None));
}

#[test]
fn prepare_upload_follows_npm_fallbacks_without_unsanitized_non_native_types() {
    let prepared = prepare_upload(jpeg_fixture(), "a.jpg", "image/jpeg").unwrap();
    assert!(prepared.sanitized);
    assert_eq!(prepared.mime_type, "image/jpeg");
    let failed = prepare_upload(vec![0xff, 0xd8, 0, 0], "a.jpg", "image/jpeg").unwrap();
    assert!(!failed.sanitized);
    assert_eq!(failed.bytes, vec![0xff, 0xd8, 0, 0]);
    let unknown = prepare_upload(b"plain".to_vec(), "a.bin", "application/octet-stream").unwrap();
    assert!(!unknown.sanitized);
    for (bytes, name, mime) in [
        (b"<svg/>".to_vec(), "a.svg", "image/svg+xml"),
        (b"%PDF-1.7".to_vec(), "a.pdf", "application/pdf"),
        (vec![0x49, 0x49, 0x2a, 0, 0], "a.tif", "image/tiff"),
        (b"PK\x03\x04".to_vec(), "a.docx", "application/octet-stream"),
    ] {
        assert!(prepare_upload(bytes, name, mime).is_err(), "{name}");
    }
}
