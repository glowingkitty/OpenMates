//! A second saved send must read its chat version after the first send's
//! admission writes. Only that chat waits; the actor and answer stream stay free.
use super::{Request, Work};
use openmates::{model::StreamUpdate, ui::Ui};
use openmates_sdk::view_model::RequestId;
use std::collections::{HashMap, VecDeque};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroize;

#[derive(Default)]
pub(super) struct SavedSendAdmissions {
    chats: HashMap<String, Admission>,
}

struct Admission {
    request: RequestId,
    admitted: bool,
    tasked: bool,
    waiting: VecDeque<Request>,
}

impl SavedSendAdmissions {
    /// New chats have no competing saved-chat write yet. For saved chats,
    /// keep one preflight in flight until its row and dispatch are known.
    pub(super) fn stage(&mut self, work: Request) -> Option<Request> {
        let Work::Send {
            request,
            chat_id: Some(chat_id),
            ..
        } = &work.work
        else {
            return Some(work);
        };
        match self.chats.entry(chat_id.clone()) {
            std::collections::hash_map::Entry::Occupied(mut entry) => {
                entry.get_mut().waiting.push_back(work);
                None
            }
            std::collections::hash_map::Entry::Vacant(entry) => {
                entry.insert(Admission {
                    request: *request,
                    admitted: false,
                    tasked: false,
                    waiting: VecDeque::new(),
                });
                Some(work)
            }
        }
    }

    /// The SDK scopes both updates to this exact turn. A task assignment
    /// follows server dispatch. For a queued turn it can come from the
    /// queue notification, which follows the durable queue status write.
    pub(super) fn observe(&mut self, request: RequestId, update: &StreamUpdate) -> Option<Request> {
        let (chat_id, admitted) = match update {
            StreamUpdate::Admitted { chat_id, .. } => (chat_id, true),
            StreamUpdate::TaskAssigned { chat_id, .. } => (chat_id, false),
            _ => return None,
        };
        let entry = self
            .chats
            .get_mut(chat_id)
            .filter(|entry| entry.request == request)?;
        if admitted {
            entry.admitted = true;
        } else {
            entry.tasked = true;
        }
        if entry.admitted && entry.tasked {
            self.complete(request)
        } else {
            None
        }
    }

    /// The final receipt also settles sends with no assistant or task frame.
    pub(super) fn complete(&mut self, request: RequestId) -> Option<Request> {
        let chat_id = self.chat_for(request)?;
        let entry = self.chats.get_mut(&chat_id)?;
        if let Some(next) = entry.waiting.pop_front() {
            let Work::Send { request, .. } = &next.work else {
                unreachable!("only saved sends are staged");
            };
            entry.request = *request;
            entry.admitted = false;
            entry.tasked = false;
            Some(next)
        } else {
            self.chats.remove(&chat_id);
            None
        }
    }

    fn chat_for(&self, request: RequestId) -> Option<String> {
        self.chats
            .iter()
            .find(|(_, entry)| entry.request == request)
            .map(|(chat, _)| chat.clone())
    }

    /// A failed admission can have an unknown write outcome. Do not advance
    /// the waiting sends behind it. The UI still owns each original draft.
    pub(super) fn fail(&mut self, request: RequestId) -> Vec<RequestId> {
        let Some(entry) = self
            .chat_for(request)
            .and_then(|chat| self.chats.remove(&chat))
        else {
            return Vec::new();
        };
        entry.waiting.into_iter().filter_map(drop_staged).collect()
    }

    pub(super) fn cancel_waiting(&mut self, request: RequestId) -> bool {
        for entry in self.chats.values_mut() {
            let Some(index) = entry.waiting.iter().position(
                |work| matches!(&work.work, Work::Send { request: id, .. } if *id == request),
            ) else {
                continue;
            };
            return entry.waiting.remove(index).and_then(drop_staged).is_some();
        }
        false
    }

    pub(super) fn clear(&mut self) -> Vec<RequestId> {
        self.chats
            .drain()
            .flat_map(|(_, entry)| entry.waiting)
            .filter_map(drop_staged)
            .collect()
    }
}

impl Drop for SavedSendAdmissions {
    fn drop(&mut self) {
        drop(self.clear());
    }
}

fn drop_staged(request: Request) -> Option<RequestId> {
    if let Work::Send {
        request,
        mut text,
        turn_cancel,
        ..
    } = request.work
    {
        text.zeroize();
        turn_cancel.cancel();
        Some(request)
    } else {
        None
    }
}

pub(super) fn retain_waiting_after_failure(
    gate: &mut SavedSendAdmissions,
    ui: &mut Ui,
    cancellations: &mut HashMap<RequestId, CancellationToken>,
    request: RequestId,
) {
    for pending in gate.fail(request) {
        cancellations.remove(&pending);
        ui.send_failed(
            pending,
            "Earlier send did not settle; this follow-up was not sent.",
        );
    }
}

pub(super) fn dispatch_released(
    gate: &mut SavedSendAdmissions,
    ui: &mut Ui,
    cancellations: &mut HashMap<RequestId, CancellationToken>,
    requests: &mpsc::Sender<Request>,
    work: Request,
) -> bool {
    match requests.try_send(work) {
        Ok(()) => true,
        Err(error) => {
            if let Some(request) = drop_staged(error.into_inner()) {
                cancellations.remove(&request);
                ui.send_failed(
                    request,
                    "The client is busy. Cancel the current operation and retry.",
                );
                retain_waiting_after_failure(gate, ui, cancellations, request);
            }
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::runtime::Stamp;
    use futures_util::{SinkExt, StreamExt};
    use serde_json::{Value, json};
    use tokio_tungstenite::tungstenite::Message;

    fn send(id: u64, chat: &str) -> Request {
        let cancel = CancellationToken::new();
        Request {
            epoch: Stamp::default(),
            work: Work::Send {
                request: RequestId(id),
                chat_id: Some(chat.into()),
                text: format!("correction {id}"),
                turn_cancel: cancel.child_token(),
            },
            cancel,
        }
    }

    fn id(work: &Request) -> RequestId {
        match &work.work {
            Work::Send { request, .. } => *request,
            _ => panic!("expected staged send"),
        }
    }

    #[tokio::test]
    async fn rapid_saved_corrections_wait_for_commit_and_receive_distinct_versions() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let peer = tokio::spawn(async move {
            let (socket, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(socket).await.unwrap();
            let mut version = 10;
            for request in [1, 2] {
                let wire = ws.next().await.unwrap().unwrap().into_text().unwrap();
                let frame: Value = serde_json::from_str(&wire).unwrap();
                assert_eq!(frame["request"], request);
                assert_eq!(frame["expected_messages_v"], version);
                version += 1;
                ws.send(Message::Text(json!({"type":"admitted"}).to_string().into()))
                    .await
                    .unwrap();
                let wire = ws.next().await.unwrap().unwrap().into_text().unwrap();
                assert_eq!(wire.as_str(), "queue committed");
                // Queue status advances the CAS version again before the queue ack.
                version += 1;
                ws.send(Message::Text(
                    json!({"type":"assigned","chat_version":version})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
            }
        });

        let (mut socket, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let mut gate = SavedSendAdmissions::default();
        let first = gate.stage(send(1, "recipe")).unwrap();
        assert!(gate.stage(send(2, "recipe")).is_none());
        assert_eq!(
            id(&gate.stage(send(3, "different-chat")).unwrap()),
            RequestId(3)
        );
        let mut next = Some(first);
        let mut version = 10;
        for request in [RequestId(1), RequestId(2)] {
            assert_eq!(id(&next.take().unwrap()), request);
            socket
                .send(Message::Text(
                    json!({"request":request.0,"expected_messages_v":version})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
            let ack = socket.next().await.unwrap().unwrap().into_text().unwrap();
            assert_eq!(
                serde_json::from_str::<Value>(&ack).unwrap()["type"],
                "admitted"
            );
            assert!(
                gate.observe(
                    request,
                    &StreamUpdate::Admitted {
                        chat_id: "recipe".into(),
                        message_id: format!("row-{}", request.0),
                    }
                )
                .is_none()
            );
            socket
                .send(Message::Text("queue committed".into()))
                .await
                .unwrap();
            let ack = socket.next().await.unwrap().unwrap().into_text().unwrap();
            let ack: Value = serde_json::from_str(&ack).unwrap();
            assert_eq!(ack["type"], "assigned");
            version = ack["chat_version"].as_u64().unwrap();
            next = gate.observe(
                request,
                &StreamUpdate::TaskAssigned {
                    chat_id: "recipe".into(),
                    message_id: format!("row-{}", request.0),
                    task_id: "still-streaming".into(),
                },
            );
        }
        assert!(next.is_none());
        assert_eq!(version, 14);
        peer.await.unwrap();
    }

    #[test]
    fn failure_or_scoped_cancel_retains_unsent_followups_without_releasing_them() {
        let mut gate = SavedSendAdmissions::default();
        gate.stage(send(1, "recipe")).unwrap();
        assert!(gate.stage(send(2, "recipe")).is_none());
        assert!(gate.stage(send(3, "recipe")).is_none());
        assert!(gate.cancel_waiting(RequestId(3)));
        assert_eq!(gate.fail(RequestId(1)), [RequestId(2)]);
        assert!(gate.complete(RequestId(1)).is_none());
        assert_eq!(id(&gate.stage(send(4, "recipe")).unwrap()), RequestId(4));
    }
}
