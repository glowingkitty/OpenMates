//! The split send on `ViewModelCore`: the turn's admission runs on the actor
//! (`openmates_sdk::view_model::begin_send_with`), its reply streams on the
//! command's task and locks the actor per phase through [`HostLease`], so
//! other commands are served meanwhile. Bindings only marshal; the split
//! itself is core (`view_model/send_stream.rs`). Plan
//! `apple-client-core-migration`; spec `client-core`.
use crate::view_core::{AppleHost, Bytes, Shared};
use crate::view_send::SendSettings;
use futures_util::future::BoxFuture;
use openmates_sdk::error::{Error, Result};
use openmates_sdk::view_model::{
    self, LeasedCore, RequestId, SendReceipt, SendTurnOptions, ViewHost, ViewLease,
};
use std::sync::Arc;
use tokio::sync::MutexGuard;
use tokio_util::sync::CancellationToken;

/// The actor state of `Shared`, locked exactly as a command locks it.
pub(crate) struct HostLease(Arc<Shared>);

impl ViewLease<Bytes> for HostLease {
    fn lease(&self) -> BoxFuture<'_, Result<LeasedCore<'_, Bytes>>> {
        Box::pin(async move {
            let guard = self.0.host.lock().await;
            let core = MutexGuard::try_map(guard, |host| host.as_mut().map(AppleHost::core_mut))
                .map_err(|_| Error::Authentication)?;
            Ok(Box::new(core) as LeasedCore<'_, Bytes>)
        })
    }
}

impl Shared {
    /// Admit the turn on the actor with Swift's send `settings` and stream
    /// its reply here, beside the actor; returns the window and receipt.
    ///
    /// # Errors
    /// `Authentication` while signed out; otherwise as `begin_send_with` and
    /// `TurnStream::run`. A session the stream found rejected signs out
    /// here, on the actor that admitted the turn only.
    pub(crate) async fn stream_send(
        self: &Arc<Self>,
        token: CancellationToken,
        settings: SendSettings,
        request: RequestId,
        chat_id: Option<String>,
        text: String,
        options: SendTurnOptions,
    ) -> Result<SendReceipt> {
        let lease: Arc<dyn ViewLease<Bytes>> = Arc::new(HostLease(self.clone()));
        let stream = self
            .signed_in(token, move |host, sink, cancel| {
                settings.apply(host);
                view_model::begin_send_with(
                    host,
                    request,
                    chat_id,
                    text,
                    options,
                    sink.clone(),
                    cancel,
                    lease,
                )
            })
            .await?;
        let owner = stream.owner();
        let result = stream.run().await;
        if result.is_ok() {
            return result;
        }
        let mut host = self.host.lock().await;
        if host
            .as_ref()
            .is_some_and(|current| owner.owns(current.core()))
        {
            return self.settle_auth(&mut host, result).await;
        }
        result
    }
}
