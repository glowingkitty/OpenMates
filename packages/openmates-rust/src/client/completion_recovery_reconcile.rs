//! Same exact assistant identity/role/version and freshly used key checks.
use super::*;
pub(super) fn reconcile_actual(job:&CompletionRecoveryJob,chat:&Chat,current_key:&[u8;32],key:&[u8;32],row:&Value)->Result<Option<CompletionRecoveryReceipt>> {
        if current_key != key {
            return Err(Error::Crypto);
        }
        let expected = job.assistant_message_id.as_deref().ok_or(Error::Protocol)?;
        let matching = chat
            .messages
            .iter()
            .filter(|message| message.id == expected)
            .collect::<Vec<_>>();
        if matching.is_empty() {
            return Ok(None);
        }
        if matching.len() != 1 || matching[0].role != "assistant" {
            return Err(Error::Protocol);
        }
        Ok(Some(CompletionRecoveryReceipt {
            job_id: job.job_id.clone(),
            chat_id: job.chat_id.clone(),
            assistant_message_id: Some(expected.into()),
            messages_version: Some(
                row["messages_v"]
                    .as_u64()
                    .filter(|v| *v > 0)
                    .ok_or(Error::Protocol)?,
            ),
            metadata_version: None,
            title_version: None,
            state: "TERMINAL".into(),
        }))
}
