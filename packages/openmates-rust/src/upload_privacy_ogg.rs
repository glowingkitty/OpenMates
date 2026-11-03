//! Ogg Opus/Vorbis comment removal (npm upload-privacy `stripOgg`). Every
//! logical stream must be understood; page CRCs are recomputed in place.
use super::{at, u32le};

struct Stream {
    serial: u32,
    packet_index: usize,
    pending_open: bool,
    pending: Vec<usize>,
    packets: Vec<Vec<usize>>,
}

fn crc_table() -> [u32; 256] {
    let mut table = [0u32; 256];
    for (i, slot) in table.iter_mut().enumerate() {
        let mut crc = (i as u32) << 24;
        for _ in 0..8 {
            crc = if crc & 0x8000_0000 != 0 {
                (crc << 1) ^ 0x04c1_1db7
            } else {
                crc << 1
            };
        }
        *slot = crc;
    }
    table
}

fn page_crc(table: &[u32; 256], bytes: &[u8], start: usize, end: usize) -> u32 {
    let mut crc = 0u32;
    for (i, byte) in bytes.iter().enumerate().take(end).skip(start) {
        let value = if i >= start + 22 && i < start + 26 {
            0
        } else {
            *byte
        };
        crc = (crc << 8) ^ table[(((crc >> 24) as u8) ^ value) as usize];
    }
    crc
}

pub(super) fn strip_ogg(bytes: &[u8]) -> Option<Vec<u8>> {
    if !at(bytes, 0, b"OggS") {
        return None;
    }
    let mut pages: Vec<(usize, usize)> = vec![];
    let mut streams: Vec<Stream> = vec![];
    let mut offset = 0usize;
    while offset < bytes.len() {
        if offset + 27 > bytes.len() || !at(bytes, offset, b"OggS") || bytes[offset + 4] != 0 {
            return None;
        }
        let segment_count = usize::from(bytes[offset + 26]);
        if offset + 27 + segment_count > bytes.len() {
            return None;
        }
        let lacing = &bytes[offset + 27..offset + 27 + segment_count];
        let data_start = offset + 27 + segment_count;
        let end = data_start + lacing.iter().map(|v| usize::from(*v)).sum::<usize>();
        if end > bytes.len() {
            return None;
        }
        let serial = u32le(bytes, offset + 14)?;
        let index = match streams.iter().position(|s| s.serial == serial) {
            Some(index) => index,
            None => {
                streams.push(Stream {
                    serial,
                    packet_index: 0,
                    pending_open: false,
                    pending: vec![],
                    packets: vec![],
                });
                streams.len() - 1
            }
        };
        let stream = &mut streams[index];
        if (bytes[offset + 5] & 1 != 0) != stream.pending_open {
            return None;
        }
        let mut cursor = data_start;
        for length in lacing.iter().map(|v| usize::from(*v)) {
            if stream.packet_index < 2 {
                stream.pending.extend(cursor..cursor + length);
            }
            cursor += length;
            stream.pending_open = length == 255;
            if length < 255 {
                let packet = std::mem::take(&mut stream.pending);
                if stream.packet_index < 2 {
                    stream.packets.push(packet);
                }
                stream.packet_index += 1;
            }
        }
        pages.push((offset, end));
        offset = end;
    }
    let mut output = bytes.to_vec();
    let mut changed = false;
    let read = |positions: &[usize], index: usize| -> Option<u8> {
        positions.get(index).map(|p| bytes[*p])
    };
    let read32 = |positions: &[usize], index: usize| -> Option<u32> {
        Some(u32::from_le_bytes([
            read(positions, index)?,
            read(positions, index + 1)?,
            read(positions, index + 2)?,
            read(positions, index + 3)?,
        ]))
    };
    let signature = |positions: &[usize], value: &[u8]| -> bool {
        positions.len() >= value.len()
            && value
                .iter()
                .enumerate()
                .all(|(i, c)| read(positions, i) == Some(*c))
    };
    for stream in &streams {
        if stream.pending_open || stream.packets.len() < 2 {
            return None;
        }
        let (first, second) = (&stream.packets[0], &stream.packets[1]);
        let opus = signature(first, b"OpusHead");
        let vorbis =
            first.len() >= 7 && read(first, 0) == Some(1) && signature(&first[1..], b"vorbis");
        // A mixed or unknown Ogg stream may carry its own comments. Do not claim
        // complete sanitization unless every logical stream is understood.
        if !opus && !vorbis {
            return None;
        }
        let prefix = if opus { 8 } else { 7 };
        let header_ok = if opus {
            signature(second, b"OpusTags")
        } else {
            read(second, 0) == Some(3) && signature(&second[1..], b"vorbis")
        };
        if second.len() < prefix + 8 || !header_ok {
            return None;
        }
        let mut cursor = prefix;
        let vendor_length = read32(second, cursor)? as usize;
        cursor += 4;
        if vendor_length > second.len().checked_sub(cursor + 4)? {
            return None;
        }
        let vendor_start = cursor;
        cursor += vendor_length;
        let comment_count = read32(second, cursor)? as usize;
        cursor += 4;
        if comment_count > (second.len() - cursor) / 4 {
            return None;
        }
        let mut comments: Vec<(usize, usize)> = vec![];
        for _ in 0..comment_count {
            if cursor + 4 > second.len() {
                return None;
            }
            let length = read32(second, cursor)? as usize;
            cursor += 4;
            if length > second.len() - cursor || (vorbis && length < 2) {
                return None;
            }
            comments.push((cursor, length));
            cursor += length;
        }
        if vorbis && (cursor >= second.len() || read(second, cursor)? & 1 == 0) {
            return None;
        }
        if opus {
            // OpusTags permits trailing padding. Clear all text and replace the two
            // length fields with an empty vendor and zero comments.
            for position in &second[prefix..] {
                output[*position] = 0;
            }
        } else {
            // Vorbis requires its framing byte at the original location. Keep every
            // length and lacing value, replacing text with valid, anonymous ASCII.
            for position in &second[vendor_start..vendor_start + vendor_length] {
                output[*position] = 0x20;
            }
            for (start, length) in &comments {
                for position in &second[*start..start + length] {
                    output[*position] = 0x20;
                }
                if *length >= 2 {
                    output[second[*start]] = 0x58;
                    output[second[start + 1]] = 0x3d;
                }
            }
            for position in &second[cursor + 1..] {
                output[*position] = 0;
            }
        }
        changed = true;
    }
    if !changed {
        return None;
    }
    let table = crc_table();
    for (start, end) in pages {
        // Recompute all pages; their sequence numbers, granules, lacing and payload
        // lengths remain byte-for-byte fixed.
        let crc = page_crc(&table, &output, start, end);
        output[start + 22..start + 26].copy_from_slice(&crc.to_le_bytes());
    }
    Some(output)
}
