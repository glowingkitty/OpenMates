use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Read};

pub const MAX_LINE: u64 = 4 * 1024 * 1024;
pub const MAX_MESSAGES: usize = 1_000;
pub const MAX_ROWS: usize = 1_000;
pub const MAX_TEXT: usize = 64 * 1024;
pub const MAX_DRAFT: usize = 8 * 1024;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub v: u8,
    pub r#type: String,
    pub epoch: u64,
    pub scope: String,
    pub state: UiState,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UiState {
    #[serde(default)]
    pub view: String,
    #[serde(default)]
    pub sidebar_open: bool,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub categories: Vec<Category>,
    #[serde(default)]
    pub chats: Vec<Chat>,
    #[serde(default)]
    pub selected_chat_id: String,
    #[serde(default)]
    pub messages: Vec<Message>,
    #[serde(default)]
    pub draft: String,
    #[serde(default)]
    pub workspace_rows: Vec<WorkspaceRow>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Category {
    pub id: String,
    pub label: String,
    #[serde(default)]
    pub color: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Chat {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub category_id: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Message {
    pub id: String,
    pub role: String,
    #[serde(default)]
    pub sender_name: Option<String>,
    #[serde(default)]
    pub content: String,
    #[serde(default)]
    pub lines: Vec<RichLine>,
    #[serde(default)]
    pub embeds: Vec<Embed>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct RichLine {
    #[serde(default)]
    pub spans: Vec<RichSpan>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct RichSpan {
    pub text: String,
    #[serde(default)]
    pub bold: bool,
    #[serde(default)]
    pub color: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Embed {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub app: String,
    #[serde(default)]
    pub color: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct WorkspaceRow {
    pub id: String,
    pub label: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default)]
    pub color: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct Action<'a> {
    pub v: u8,
    pub r#type: &'static str,
    pub epoch: u64,
    pub scope: &'a str,
    pub action: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub open: Option<bool>,
}

impl Snapshot {
    pub fn validate(&self) -> Result<(), String> {
        if self.v != 1 || self.r#type != "snapshot" {
            return Err("expected v1 snapshot".into());
        }
        if self.scope.is_empty() || self.scope.len() > 256 || !self.scope.is_ascii() {
            return Err("invalid scope".into());
        }
        let s = &self.state;
        if s.messages.len() > MAX_MESSAGES
            || s.chats.len() > MAX_ROWS
            || s.workspace_rows.len() > MAX_ROWS
            || s.categories.len() > 64
            || s.draft.len() > MAX_DRAFT
            || s.title.len() > 512
        {
            return Err("snapshot count or field limit exceeded".into());
        }
        for m in &s.messages {
            if m.content.len() > MAX_TEXT
                || m.sender_name.as_ref().is_some_and(|name| name.len() > 256)
                || m.lines.len() > MAX_ROWS
                || m.embeds.len() > 128
            {
                return Err("message limit exceeded".into());
            }
            if m.lines.iter().any(|line| {
                line.spans.len() > 256 || line.spans.iter().any(|x| x.text.len() > MAX_TEXT)
            }) {
                return Err("rich line limit exceeded".into());
            }
        }
        Ok(())
    }
}

/// Read a bounded JSONL frame; overlong frames are drained before the next frame.
pub fn read_frame<R: BufRead>(reader: &mut R) -> io::Result<Option<Vec<u8>>> {
    let mut line = Vec::new();
    let bytes = (&mut *reader)
        .take(MAX_LINE + 1)
        .read_until(b'\n', &mut line)?;
    if bytes == 0 {
        return Ok(None);
    }
    if line.len() as u64 > MAX_LINE {
        if !line.ends_with(b"\n") {
            loop {
                let available = reader.fill_buf()?;
                if available.is_empty() {
                    break;
                }
                let newline = available.iter().position(|b| *b == b'\n');
                let count = newline.map_or(available.len(), |index| index + 1);
                reader.consume(count);
                if newline.is_some() {
                    break;
                }
            }
        }
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "frame too large",
        ));
    }
    Ok(Some(line))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn rejects_oversized_frame_then_recovers() {
        let mut data = vec![b'x'; MAX_LINE as usize + 1];
        data.extend_from_slice(b"\n{}\n");
        let mut cursor = Cursor::new(data);
        assert!(read_frame(&mut cursor).is_err());
        assert_eq!(read_frame(&mut cursor).unwrap(), Some(b"{}\n".to_vec()));
    }

    #[test]
    fn rejects_unbounded_messages() {
        let mut snapshot = Snapshot {
            v: 1,
            r#type: "snapshot".into(),
            scope: "chat:x".into(),
            ..Default::default()
        };
        snapshot
            .state
            .messages
            .resize_with(MAX_MESSAGES + 1, Default::default);
        assert!(snapshot.validate().is_err());
    }

    #[test]
    fn accepts_optional_sender_name_wire_field() {
        let named: Message =
            serde_json::from_str(r#"{"id":"m1","role":"user","senderName":"Alex"}"#).unwrap();
        let unnamed: Message = serde_json::from_str(r#"{"id":"m2","role":"assistant"}"#).unwrap();
        assert_eq!(named.sender_name.as_deref(), Some("Alex"));
        assert_eq!(unnamed.sender_name, None);
        assert_eq!(serde_json::to_value(named).unwrap()["senderName"], "Alex");
    }
}
