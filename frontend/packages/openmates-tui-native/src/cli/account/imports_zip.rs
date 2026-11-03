//! Read-only archive access for account imports: a minimal ZIP reader (stored
//! and deflate entries, as produced by provider exports and the OpenMates
//! export writer) and the npm "OMZIP1" scrypt + AES-256-GCM container opener.
use std::io::Read;

const ENCRYPTED_MAGIC: &str = "OMZIP1";
/// Refuse to inflate a single entry beyond this size (decompression bombs).
const MAX_ENTRY_BYTES: u64 = 2 * 1024 * 1024 * 1024;

pub(super) struct ZipEntry {
    pub name: String,
    method: u16,
    compressed: usize,
    uncompressed: u64,
    local_offset: usize,
}

pub(super) struct ZipArchive<'a> {
    data: &'a [u8],
    pub entries: Vec<ZipEntry>,
}

fn u16_at(data: &[u8], at: usize) -> Result<u16, String> {
    data.get(at..at + 2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .ok_or_else(|| "Corrupted zip: unexpected end of data".to_owned())
}
fn u32_at(data: &[u8], at: usize) -> Result<u32, String> {
    data.get(at..at + 4)
        .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .ok_or_else(|| "Corrupted zip: unexpected end of data".to_owned())
}

pub(super) fn is_zip(data: &[u8]) -> bool {
    data.starts_with(b"PK")
}

impl<'a> ZipArchive<'a> {
    pub(super) fn open(data: &'a [u8]) -> Result<Self, String> {
        let floor = data.len().saturating_sub(22 + 65_535);
        let end = (floor..=data.len().saturating_sub(22))
            .rev()
            .find(|&at| data[at..].starts_with(&[0x50, 0x4b, 0x05, 0x06]))
            .ok_or("End of data reached (data length = 0, asked index = 0). Corrupted zip?")?;
        let count = usize::from(u16_at(data, end + 10)?);
        let mut at = u32_at(data, end + 16)? as usize;
        if count == 0xffff || at == 0xffff_ffff {
            return Err("ZIP64 archives are not supported.".into());
        }
        let mut entries = Vec::with_capacity(count);
        for _ in 0..count {
            if u32_at(data, at)? != 0x0201_4b50 {
                return Err("Corrupted zip: missing central directory signature".into());
            }
            let name_len = usize::from(u16_at(data, at + 28)?);
            let extra_len = usize::from(u16_at(data, at + 30)?);
            let comment_len = usize::from(u16_at(data, at + 32)?);
            let name = data
                .get(at + 46..at + 46 + name_len)
                .ok_or("Corrupted zip: truncated entry name")?;
            entries.push(ZipEntry {
                name: String::from_utf8_lossy(name).into_owned(),
                method: u16_at(data, at + 10)?,
                compressed: u32_at(data, at + 20)? as usize,
                uncompressed: u64::from(u32_at(data, at + 24)?),
                local_offset: u32_at(data, at + 42)? as usize,
            });
            at += 46 + name_len + extra_len + comment_len;
        }
        Ok(Self { data, entries })
    }

    pub(super) fn names(&self) -> Vec<String> {
        self.entries.iter().map(|e| e.name.clone()).collect()
    }

    pub(super) fn read(&self, entry: &ZipEntry) -> Result<Vec<u8>, String> {
        let at = entry.local_offset;
        if u32_at(self.data, at)? != 0x0403_4b50 {
            return Err("Corrupted zip: missing local file header".into());
        }
        let start = at
            + 30
            + usize::from(u16_at(self.data, at + 26)?)
            + usize::from(u16_at(self.data, at + 28)?);
        let raw = self
            .data
            .get(start..start + entry.compressed)
            .ok_or("Corrupted zip: truncated entry data")?;
        if entry.uncompressed > MAX_ENTRY_BYTES {
            return Err("Import archive entry is too large.".into());
        }
        let out = match entry.method {
            0 => raw.to_vec(),
            8 => {
                let mut out = Vec::new();
                flate2::read::DeflateDecoder::new(raw)
                    .take(MAX_ENTRY_BYTES + 1)
                    .read_to_end(&mut out)
                    .map_err(|e| format!("Corrupted zip: {e}"))?;
                out
            }
            other => return Err(format!("Corrupted zip: compression {other} not supported")),
        };
        if out.len() as u64 != entry.uncompressed {
            return Err("Corrupted zip: uncompressed data size mismatch".into());
        }
        Ok(out)
    }

    /// The exact entry, else the first real file with that basename
    /// (skipping macOS resource forks), like the legacy `readZipText`.
    pub(super) fn find_text(&self, required: &str) -> Result<String, String> {
        let entry = self
            .entries
            .iter()
            .find(|e| e.name == required)
            .or_else(|| {
                self.entries.iter().find(|e| {
                    !e.name.ends_with('/')
                        && !e.name.starts_with("__MACOSX/")
                        && !e.name.contains("/._")
                        && !e.name.starts_with("._")
                        && e.name.rsplit('/').next() == Some(required)
                })
            });
        let entry = entry.ok_or_else(|| format!("Import archive is missing {required}"))?;
        Ok(String::from_utf8_lossy(&self.read(entry)?).into_owned())
    }

    pub(super) fn exact_text(&self, name: &str) -> Result<Option<String>, String> {
        match self.entries.iter().find(|e| e.name == name) {
            Some(entry) => Ok(Some(
                String::from_utf8_lossy(&self.read(entry)?).into_owned(),
            )),
            None => Ok(None),
        }
    }
}

/// npm `decryptOpenMatesEncryptedZip`: plain payloads pass through unchanged.
pub(super) fn decrypt_openmates_zip(
    payload: Vec<u8>,
    password: Option<&str>,
) -> Result<Vec<u8>, String> {
    use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
    use base64::{Engine, engine::general_purpose::STANDARD};
    let prefix = format!("{ENCRYPTED_MAGIC}\n");
    if !payload.starts_with(prefix.as_bytes()) {
        return Ok(payload);
    }
    let password = password.ok_or("OpenMates encrypted export requires a password.")?;
    let length_end = payload[prefix.len()..]
        .iter()
        .position(|b| *b == b'\n')
        .map(|p| p + prefix.len())
        .ok_or("OpenMates encrypted export has an invalid header.")?;
    let header_len = std::str::from_utf8(&payload[prefix.len()..length_end])
        .ok()
        .and_then(|s| s.trim().parse::<usize>().ok())
        .filter(|n| *n > 0)
        .ok_or("OpenMates encrypted export has an invalid header length.")?;
    let header_end = (length_end + 1)
        .checked_add(header_len)
        .filter(|end| *end <= payload.len())
        .ok_or("OpenMates encrypted export has an invalid header.")?;
    let header: serde_json::Value =
        serde_json::from_slice(&payload[length_end + 1..header_end]).map_err(|e| e.to_string())?;
    if header["magic"] != ENCRYPTED_MAGIC
        || header["cipher"] != "aes-256-gcm"
        || header["kdf"] != "scrypt"
    {
        return Err("OpenMates encrypted export uses an unsupported encryption format.".into());
    }
    let field = |name: &str| {
        STANDARD
            .decode(header[name].as_str().unwrap_or(""))
            .map_err(|_| "OpenMates encrypted export has an invalid header.".to_owned())
    };
    let (salt, iv, tag) = (field("salt")?, field("iv")?, field("tag")?);
    if iv.len() != 12 || tag.len() != 16 {
        return Err("OpenMates encrypted export has an invalid header.".into());
    }
    let mut key = zeroize::Zeroizing::new([0u8; 32]);
    let params = scrypt::Params::new(14, 8, 1, 32).map_err(|e| e.to_string())?;
    scrypt::scrypt(password.as_bytes(), &salt, &params, key.as_mut()).map_err(|e| e.to_string())?;
    let mut sealed = payload[header_end..].to_vec();
    sealed.extend_from_slice(&tag);
    Aes256Gcm::new_from_slice(key.as_ref())
        .map_err(|e| e.to_string())?
        .decrypt(Nonce::from_slice(&iv), sealed.as_slice())
        .map_err(|_| {
            "OpenMates encrypted export could not be decrypted: Unsupported state or unable to authenticate data".to_owned()
        })
}
