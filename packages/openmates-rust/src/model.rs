//! Decrypted presentation types. Credential and key objects never enter UI fields.
use serde::{Deserialize, Serialize};
use serde_json::Value;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Workspace {
    #[default]
    Chats,
    Apps,
    Projects,
    Workflows,
    Tasks,
    Settings,
}
impl Workspace {
    pub const ALL: [Self; 6] = [
        Self::Chats,
        Self::Apps,
        Self::Projects,
        Self::Workflows,
        Self::Tasks,
        Self::Settings,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Self::Chats => "Chats",
            Self::Apps => "Apps",
            Self::Projects => "Projects",
            Self::Workflows => "Workflows",
            Self::Tasks => "Tasks",
            Self::Settings => "Settings",
        }
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Item {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub category: String,
    /// Workspace-specific metadata. Chat inventory results always include
    /// `chat_list_title`: the exact decrypted title string (including empty),
    /// or null when no canonical title is available in the current key scope.
    /// `title` remains the display string, including draft/locked fallbacks.
    #[serde(default)]
    pub fields: Value,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Message {
    pub id: String,
    pub role: String,
    pub content: String,
    #[serde(default)]
    pub sender: String,
    #[serde(default)]
    pub thinking: String,
    #[serde(default)]
    pub embeds: Vec<Item>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Chat {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub messages: Vec<Message>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum StreamUpdate {
    Consent {
        request_id: String,
        items: Vec<Item>,
    },
    Started {
        chat_id: String,
        message_id: String,
        expects_reply: bool,
    },
    /// Dispatch may have committed: do not automatically resend after failure.
    Submitted {
        chat_id: String,
        message_id: String,
    },
    /// The server acknowledged persistence of this encrypted user message.
    Admitted {
        chat_id: String,
        message_id: String,
    },
    Content {
        content: String,
        thinking: String,
        mate: String,
    },
    Completed {
        chat_id: String,
        message_id: String,
        content: String,
    },
    Status(String),
    /// The server task that answers this turn became known (the first
    /// `ai_task_initiated`/turn frame naming it, before any reply text). Shells
    /// pass it to stop requests; it repeats only when the turn hands over to a
    /// continuation task.
    TaskAssigned {
        chat_id: String,
        message_id: String,
        task_id: String,
    },
}
pub(crate) fn zeroize_json(v:&mut Value){
    use zeroize::Zeroize;
    match v {
        Value::String(s)=>s.zeroize(),
        Value::Array(a)=>{for v in a.iter_mut(){zeroize_json(v);}},
        Value::Object(o)=>{for(mut k,mut v)in std::mem::take(o){k.zeroize();zeroize_json(&mut v);}},
        _=>{},
    }
    *v=Value::Null;
}
/// Erase a discarded in-memory update; serialization/wire types stay unchanged.
impl zeroize::Zeroize for StreamUpdate {
    fn zeroize(&mut self) {
        match self {
            Self::Started{chat_id,message_id,expects_reply}=>{chat_id.zeroize();message_id.zeroize();expects_reply.zeroize();},
            Self::Submitted{chat_id,message_id}|Self::Admitted{chat_id,message_id}=>{chat_id.zeroize();message_id.zeroize();},
            Self::Content{content,thinking,mate}=>{content.zeroize();thinking.zeroize();mate.zeroize();},
            Self::Completed{chat_id,message_id,content}=>{chat_id.zeroize();message_id.zeroize();content.zeroize();},
            Self::Status(s)=>s.zeroize(),
            Self::TaskAssigned{chat_id,message_id,task_id}=>{chat_id.zeroize();message_id.zeroize();task_id.zeroize();},
            Self::Consent{request_id,items}=>{request_id.zeroize();for item in items.iter_mut(){item.id.zeroize();item.title.zeroize();item.description.zeroize();item.status.zeroize();item.category.zeroize();zeroize_json(&mut item.fields);}items.clear();},
        }
    }
}
#[cfg(test)]
mod discarded_stream_erasure_tests {
    use super::*;
    use zeroize::Zeroize;
    #[test]
    fn discarded_content_is_empty_before_release(){
        let mut update=StreamUpdate::Content{content:"synthetic-private-text".into(),thinking:"synthetic-private-thinking".into(),mate:"synthetic".into()};update.zeroize();
        assert!(matches!(update,StreamUpdate::Content{content,thinking,mate} if content.is_empty()&&thinking.is_empty()&&mate.is_empty()));
    }
    #[test]
    fn discarded_consent_erases_nested_fields_and_identifiers(){
        let mut update=StreamUpdate::Consent{request_id:"synthetic".into(),items:vec![Item{title:"private".into(),fields:serde_json::json!({"private-key":[{"value":"private"}]}),..Default::default()}]};update.zeroize();
        assert!(matches!(update,StreamUpdate::Consent{request_id,items} if request_id.is_empty()&&items.is_empty()));
    }
}
#[derive(Clone, Debug)]
pub enum Mutation {
    Create {
        workspace: Workspace,
        fields: Value,
    },
    Update {
        workspace: Workspace,
        id: String,
        fields: Value,
    },
    Delete {
        workspace: Workspace,
        id: String,
    },
    RunWorkflow {
        id: String,
    },
    SetSetting {
        section: String,
        fields: Value,
    },
}
