// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
use super::*;

fn le(value: u32) -> [u8; 4] {
    value.to_le_bytes()
}

#[test]
fn upload_mime_mapping_and_extname_match_npm() {
    for (name, mime) in [
        ("memo.MP3", "audio/mpeg"),
        ("a.m4a", "audio/mp4"),
        ("a.mp4", "audio/mp4"),
        ("a.wav", "audio/wav"),
        ("a.webm", "audio/webm"),
        ("a.oga", "audio/ogg"),
        ("a.ogg", "audio/ogg"),
        ("a.aac", "audio/aac"),
        ("a.jpeg", "image/jpeg"),
        ("a.pdf", "application/pdf"),
        ("a.flac", "application/octet-stream"),
        (".wav", "application/octet-stream"),
        ("noext", "application/octet-stream"),
    ] {
        assert_eq!(upload_mime_type(name), mime, "{name}");
    }
    assert_eq!(js_extname(".env"), "");
    assert_eq!(js_extname("a."), ".");
    assert_eq!(js_extname("a.tar.gz"), ".gz");
}

#[test]
fn detection_prefers_magic_bytes_then_declared_type() {
    assert_eq!(
        detect_mime_type(b"ID3\x04rest", "audio/aac", "a.aac"),
        "audio/aac"
    );
    assert_eq!(
        detect_mime_type(b"ID3\x04rest", "audio/mpeg", "a.mp3"),
        "audio/mpeg"
    );
    assert_eq!(
        detect_mime_type(b"\0\0\0\x18ftypM4A rest", "audio/mp4", "a.m4a"),
        "audio/mp4"
    );
    assert_eq!(
        detect_mime_type(b"\0\0\0\x18ftypheic", "audio/mp4", "a.m4a"),
        "image/heic"
    );
    assert_eq!(
        detect_mime_type(&[0xff, 0xd8, 0xff], "audio/mpeg", "a.mp3"),
        "image/jpeg"
    );
    assert_eq!(
        detect_mime_type(b"xyz", "application/octet-stream", "a.oga"),
        "audio/ogg"
    );
    assert_eq!(
        detect_mime_type(b"xyz", "audio/mpeg", "a.mp3"),
        "audio/mpeg"
    );
    // A renamed image is refused: only audio sanitizers are native.
    assert!(prepare_audio_upload(vec![0xff, 0xd8, 0xff, 0xe0], "photo.mp3").is_err());
}

fn wav(extra: &[u8]) -> Vec<u8> {
    let mut body = b"WAVE".to_vec();
    body.extend(b"fmt ");
    body.extend(le(16));
    body.extend([1, 0, 1, 0, 0x40, 0x1f, 0, 0, 0x80, 0x3e, 0, 0, 2, 0, 16, 0]);
    body.extend(extra);
    body.extend(b"data");
    body.extend(le(4));
    body.extend([1, 2, 3, 4]);
    let mut file = b"RIFF".to_vec();
    file.extend(le(body.len() as u32));
    file.extend(body);
    file
}

#[test]
fn wav_info_chunks_are_removed_and_sizes_rewritten() {
    let mut list = b"LIST".to_vec();
    list.extend(le(12));
    list.extend(b"INFOIART\x04\0\0\0");
    let cleaned = strip_audio_metadata(&wav(&list), "audio/wav").unwrap();
    assert_eq!(cleaned, wav(&[]));
    let prepared = prepare_audio_upload(wav(&list), "memo.wav").ok().unwrap();
    assert!(prepared.sanitized);
    assert_eq!(prepared.mime_type, "audio/wav");
    assert_eq!(prepared.bytes, wav(&[]));
    // Truncated or unknown containers keep the original (unsanitized) bytes.
    let broken = prepare_audio_upload(b"RIFF\0\0\0\0WAVE".to_vec(), "x.wav")
        .ok()
        .unwrap();
    assert!(!broken.sanitized);
}

#[test]
fn mp3_id3_ape_and_id3v1_tags_are_removed() {
    let frame = [0xff, 0xfb, 0x90, 0x64, 0, 0, 0, 0];
    let mut file = b"ID3\x04\0\0\0\0\0\x03abc".to_vec();
    file.extend(frame);
    let mut tag = b"TAG".to_vec();
    tag.resize(128, b'x');
    file.extend(&tag);
    assert_eq!(strip_audio_metadata(&file, "audio/mpeg").unwrap(), frame);
    assert_eq!(strip_audio_metadata(&frame, "audio/mpeg").unwrap(), frame);
    assert_eq!(
        strip_audio_metadata(b"ID3\x04\0\0\0\0\0\x7fab", "audio/mpeg"),
        None
    );
}

fn atom(kind: &[u8; 4], payload: &[u8]) -> Vec<u8> {
    let mut out = ((payload.len() + 8) as u32).to_be_bytes().to_vec();
    out.extend(kind);
    out.extend(payload);
    out
}

#[test]
fn mp4_metadata_atoms_become_zeroed_free_atoms() {
    let ftyp = atom(b"ftyp", b"M4A \0\0\0\0");
    let udta = atom(b"udta", b"secret-name");
    let moov = atom(b"moov", &[atom(b"mvhd", &[0; 4]), udta.clone()].concat());
    let file = [ftyp.clone(), moov, atom(b"mdat", &[7; 4])].concat();
    let cleaned = strip_audio_metadata(&file, "audio/mp4").unwrap();
    let free = atom(b"free", &[0; 11]);
    let expected_moov = atom(b"moov", &[atom(b"mvhd", &[0; 4]), free].concat());
    assert_eq!(
        cleaned,
        [ftyp, expected_moov, atom(b"mdat", &[7; 4])].concat()
    );
    assert!(!cleaned.windows(6).any(|w| w == b"secret"));
}

#[test]
fn webm_tags_are_voided() {
    let ebml = [0x1a, 0x45, 0xdf, 0xa3, 0x80];
    let tags = [0x12, 0x54, 0xc3, 0x67, 0x83, b'a', b'b', b'c'];
    let mut segment = vec![0x18, 0x53, 0x80, 0x67, 0x80 | tags.len() as u8];
    segment.extend(tags);
    let file = [ebml.to_vec(), segment.clone()].concat();
    let cleaned = strip_audio_metadata(&file, "audio/webm").unwrap();
    assert_eq!(&cleaned[..10], &file[..10]);
    assert_eq!(&cleaned[10..], &[0xec, 0x86, 0, 0, 0, 0, 0, 0]);
}

fn ogg_page(serial: u32, flags: u8, sequence: u32, packet: &[u8]) -> Vec<u8> {
    assert!(packet.len() < 255);
    let mut page = b"OggS\0".to_vec();
    page.push(flags);
    page.extend([0; 8]);
    page.extend(le(serial));
    page.extend(le(sequence));
    page.extend([0; 4]);
    page.push(1);
    page.push(packet.len() as u8);
    page.extend(packet);
    page
}

#[test]
fn opus_tags_are_cleared_and_page_crcs_recomputed() {
    let head = [
        b"OpusHead".to_vec(),
        vec![1, 1, 0, 0, 0x80, 0xbb, 0, 0, 0, 0, 0],
    ]
    .concat();
    let mut tags = b"OpusTags".to_vec();
    tags.extend(le(4));
    tags.extend(b"lame");
    tags.extend(le(1));
    tags.extend(le(9));
    tags.extend(b"ARTIST=me");
    let file = [ogg_page(7, 2, 0, &head), ogg_page(7, 0, 1, &tags)].concat();
    let cleaned = strip_audio_metadata(&file, "audio/ogg").unwrap();
    assert!(!cleaned.windows(6).any(|w| w == b"ARTIST"));
    let second = ogg_page(7, 0, 1, &tags).len();
    let start = cleaned.len() - second;
    assert_eq!(&cleaned[start + 28..start + 36], b"OpusTags");
    assert!(cleaned[start + 36..].iter().all(|b| *b == 0));
    // Byte-identical to the npm upload-privacy output, including both CRCs.
    let hex: String = cleaned.iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(
        hex,
        "4f67675300020000000000000000070000000000000019f819d201134f707573486561640101000080bb00000000004f676753000000000000000000000700000001000000c834f29801214f7075735461677300000000000000000000000000000000000000000000000000"
    );
    // Unknown codecs are not claimed as sanitized.
    let unknown = [ogg_page(7, 2, 0, b"Speex   xx"), ogg_page(7, 0, 1, &tags)].concat();
    assert_eq!(strip_audio_metadata(&unknown, "audio/ogg"), None);
}
