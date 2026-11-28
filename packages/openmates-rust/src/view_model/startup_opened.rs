//! Native startup selects the last admitted open before general reconciliation.
//! The local fallback and remote completion are cancellable and share the
//! ordinary exact chat reader. Hydration never registers another user open.
use super::{
    ChatWindowSource, RequestId, ViewCore, ViewEvent, ViewSink, actor::StartupMonitorCohort,
    actor_flows::publish_startup_sidebar, actor_host::ViewHost,
};
use crate::{
    client::StartupForegroundBudget,
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

const STARTUP_FOREGROUND_TIMEOUT: Duration = Duration::from_secs(1);

/// Publish only the last-known selected cache window, before startup network
/// reconciliation. A missing local transcript simply leaves selection pending.
///
/// # Errors
/// Cache or publication failure, or cancellation of the original scope.
pub fn paint_startup_chat<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let core = host.core_mut();
        if !core.recently_opened_enabled
            || core.explicit_startup_navigation
            || core.open_chat_id().is_some()
        {
            return Ok(());
        }
        let Some(id) = core.client().cached_startup_chat_id() else {
            return Ok(());
        };
        core.begin_client_operation(cancel);
        if let Some(window) = core.cached_window(&id, cancel).await? {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            core.begin_window(request, &id);
            sink.emit(
                core.publish_window(request, window)
                    .ok_or(Error::Cancelled)?,
            )
            .await?;
        }
        Ok(())
    })
}

/// Refresh the authoritative last-opened selection. Return the ordered IDs
/// to hydrate after the foreground result has been delivered. An explicit
/// selection cancels startup and cannot be replaced by a late resume.
///
/// # Errors
/// Admission or protocol failure, or a revoked/cancelled operation.
pub fn resume_startup_chat<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Vec<String>>> {
    Box::pin(resume_startup_with_budget(
        host,
        request,
        sink,
        cancel,
        STARTUP_FOREGROUND_TIMEOUT,
    ))
}

async fn resume_startup_with_budget<S: ByteStore + 'static, H: ViewHost<S>>(
    host: &mut H,
    request: RequestId,
    sink: &H::Sink,
    cancel: &CancellationToken,
    timeout: Duration,
) -> Result<Vec<String>> {
    let core = host.core_mut();
    if !core.recently_opened_enabled {
        return Ok(Vec::new());
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    if core.startup_resume_completed {
        return Ok(core.startup_hydration.clone());
    }
    let generation = core.shell().ops().guard();
    let needs_sidebar =
        !core.startup_sidebar_published && core.client().needs_startup_recent_chats()?;
    let budget = needs_sidebar.then(|| StartupForegroundBudget::new(timeout, cancel));
    let cancellable = StartupForegroundBudget::cancellable(cancel);
    core.begin_client_operation(cancel);
    let mut ids = core
        .client_mut()
        .refresh_startup_opened_chat_ids(Some(budget.as_ref().unwrap_or(&cancellable)))
        .await;
    if budget
        .as_ref()
        .is_some_and(StartupForegroundBudget::deferred)
    {
        publish_startup_sidebar(host, sink, cancel).await?;
        host.core_mut().begin_client_operation(cancel);
        ids = host
            .core_mut()
            .client_mut()
            .refresh_startup_opened_chat_ids(Some(&cancellable))
            .await;
    }
    let ids = match ids {
        Ok(ids) => ids,
        Err(Error::Offline) => {
            publish_startup_sidebar(host, sink, cancel).await?;
            return Ok(Vec::new());
        }
        Err(error @ (Error::Protocol | Error::Invalid(_))) => {
            // Report the original selector error after giving the independent
            // metadata lane its chance. Admission denials abort immediately.
            publish_startup_sidebar(host, sink, cancel).await?;
            return Err(error);
        }
        Err(error) => return Err(error),
    };
    if cancel.is_cancelled() || !generation.is_current() {
        return Err(Error::Cancelled);
    }

    let mut head_settled = false;
    if !host.core().explicit_startup_navigation
        && let Some(id) = ids.first()
    {
        let core = host.core_mut();
        if let Some(window) = core.window.as_mut().filter(|window| window.chat_id == *id) {
            // Keep cached rows available while the same selection refreshes.
            window.request = request;
        } else {
            core.begin_window(request, id);
        }
        let bounded = budget.as_ref().filter(|budget| !budget.deferred());
        let mut result = core
            .read_window_policy(
                request,
                id,
                sink,
                cancel,
                true,
                false,
                Some(bounded.unwrap_or(&cancellable)),
            )
            .await;
        if bounded.is_some_and(StartupForegroundBudget::deferred)
            && matches!(&result, Ok(_) | Err(Error::Offline))
        {
            publish_startup_sidebar(host, sink, cancel).await?;
            if cancel.is_cancelled() || !generation.is_current() {
                return Err(Error::Cancelled);
            }
            let core = host.core_mut();
            if core
                .open_window()
                .is_some_and(|window| window.source == ChatWindowSource::FirstPage)
            {
                // Already painted fresh rows. Let the normal background cohort
                // complete the rest after the sidebar has had its turn.
                result = Err(Error::Offline);
            } else {
                core.begin_client_operation(cancel);
                result = core
                    .read_window_policy(request, id, sink, cancel, true, false, Some(&cancellable))
                    .await;
            }
        }
        if cancel.is_cancelled() || !generation.is_current() {
            return Err(Error::Cancelled);
        }
        match result {
            Ok(window) => {
                head_settled =
                    window.source == ChatWindowSource::Canonical && window.history_complete;
                sink.emit(
                    host.core_mut()
                        .publish_window(request, window)
                        .ok_or(Error::Cancelled)?,
                )
                .await?;
                if head_settled {
                    host.core_mut()
                        .client_mut()
                        .retain_automatically_hydrated_history(id, false);
                }
            }
            Err(Error::Forbidden) => {
                head_settled = true;
                host.core_mut().close_chat(id);
                sink.emit(ViewEvent::ChatUnavailable {
                    chat_id: id.clone(),
                })
                .await?;
                // Preserve a Team revocation or account/scope denial; the
                // startup queue must not use it as permission to continue.
                if host.core().client().session().is_none()
                    || host
                        .core()
                        .client()
                        .session()
                        .is_some_and(|session| session.active_team_id.is_some())
                {
                    return Err(Error::Forbidden);
                }
            }
            Err(Error::Offline) => {}
            Err(error @ (Error::Protocol | Error::Invalid(_))) => {
                publish_startup_sidebar(host, sink, cancel).await?;
                return Err(error);
            }
            Err(error) => return Err(error),
        }
    }
    publish_startup_sidebar(host, sink, cancel).await?;
    let core = host.core_mut();
    core.persist().await?;
    if cancel.is_cancelled() || !generation.is_current() {
        return Err(Error::Cancelled);
    }
    core.startup_resume_completed = true;
    // A readable first page can still lack older offline history. Keep it
    // first in the hydration queue until it is complete or access is denied.
    core.startup_hydration = ids.into_iter().skip(usize::from(head_settled)).collect();
    Ok(core.startup_hydration.clone())
}

/// Restore an already selected Team during bootstrap without starting the
/// normal metadata list. The exact Team is checked online before admission or
/// paint, and its existing encrypted index is restored before the first save.
///
/// # Errors
/// Cancellation, Team authorization, cache restore or admission errors.
pub fn switch_team_for_startup<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    team: Option<String>,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let core = host.core_mut();
        let generation = core.shell().ops().guard();
        let previous = core.client().session().ok_or(Error::Authentication)?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if previous.active_team_id == team {
            return Ok(());
        }
        core.retire_window();
        core.explicit_startup_navigation = false;
        core.startup_resume_completed = false;
        core.startup_sidebar_published = false;
        core.startup_monitor_cohort = StartupMonitorCohort::Initial;
        core.startup_hydration.clear();
        core.set_chat_monitor(None);
        core.client_mut().set_team(team.as_deref())?;
        core.begin_client_operation(cancel);
        core.client_mut().validate_startup_team().await?;
        if !generation.is_current() || cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // The scoped credentials are the previously admitted profile with
        // only its authorized Team selector changed. Restore before admit,
        // which durably persists the new scope and may rotate cookies.
        let scoped = core.client().clone_session().ok_or(Error::Authentication)?;
        core.restore_index(&scoped, cancel).await?;
        host.admit(sink).await?;
        if !generation.is_current() || cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(())
    })
}

/// Refresh the admitted startup selector and its versions without selecting
/// or reopening any chat. The shell schedules this only after reconnect.
///
/// # Errors
/// Transport, admission, persistence or cancellation errors.
#[doc(hidden)]
pub fn refresh_startup_cohort<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Vec<String>>> {
    Box::pin(host.core_mut().refresh_startup_cohort(cancel))
}

/// Fill the ordered retained chats with exact encrypted text history. Run
/// after the selected window. Interruption leaves earlier durable items intact.
///
/// # Errors
/// Revoked authority, cancellation or a durable cache error.
pub fn hydrate_startup_chats<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    ids: Vec<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let evict = host.recovery_idle().await;
        match host
            .core_mut()
            .hydrate_startup_cohort(&ids, evict, cancel)
            .await
        {
            Err(Error::Offline) => Ok(()),
            outcome => outcome,
        }
    })
}

impl<S: ByteStore + 'static> ViewCore<S> {
    async fn refresh_startup_cohort(&mut self, cancel: &CancellationToken) -> Result<Vec<String>> {
        if !self.recently_opened_enabled {
            return Ok(Vec::new());
        }
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let generation = self.shell().ops().guard();
        let cancellable = StartupForegroundBudget::cancellable(cancel);
        self.begin_client_operation(cancel);
        let ids = self
            .client_mut()
            .refresh_startup_opened_chat_ids(Some(&cancellable))
            .await?;
        if !generation.is_current() || cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.persist().await?;
        if !generation.is_current() || cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.startup_resume_completed = true;
        self.startup_hydration.clone_from(&ids);
        Ok(ids)
    }

    /// Run a replacement monitor's cohort after its ordinary live publication.
    /// Preemption retains the unfinished queue, and a new connection reprobes it.
    pub(super) async fn refresh_monitor_startup_cohort(
        &mut self,
        cancel: &CancellationToken,
    ) -> Result<()> {
        if matches!(
            self.startup_monitor_cohort,
            StartupMonitorCohort::Initial | StartupMonitorCohort::Connected
        ) {
            return Ok(());
        }
        let result = async {
            if matches!(self.startup_monitor_cohort, StartupMonitorCohort::Refresh) {
                self.refresh_startup_cohort(cancel).await?;
                self.startup_monitor_cohort = StartupMonitorCohort::Hydrate;
            }
            let ids = self.startup_hydration.clone();
            // The live monitor has no authority to evict while work may be pending.
            self.hydrate_startup_cohort(&ids, false, cancel).await
        }
        .await;
        if result != Err(Error::Cancelled) {
            // Report a failed cohort once. The live list's own retry does not
            // reopen the cohort until the next genuinely replacement monitor.
            self.startup_monitor_cohort = StartupMonitorCohort::Connected;
        }
        result
    }

    async fn hydrate_startup_cohort(
        &mut self,
        ids: &[String],
        evict: bool,
        cancel: &CancellationToken,
    ) -> Result<()> {
        // A stale list after a scope switch cannot admit reads.
        let ids: Vec<_> = self
            .startup_hydration
            .iter()
            .filter(|id| ids.contains(id))
            .cloned()
            .collect();
        for id in ids {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            self.begin_client_operation(cancel);
            self.restore_selected_cache_section(&id, cancel).await?;
            let generation = self.session.ops().guard();
            match self
                .client
                .hydrate_opened_chat(self.monitor.as_ref(), &id, cancel)
                .await
            {
                Ok(Some(candidate)) => {
                    self.client.validate_chat_view(&candidate)?;
                    let _receipt = self
                        .session
                        .persist_for(&mut self.client, &*self.credentials, &candidate)
                        .await?;
                    if !generation.is_current() || cancel.is_cancelled() {
                        return Err(Error::Cancelled);
                    }
                    self.client_mut()
                        .retain_automatically_hydrated_history(&id, evict);
                    self.persist().await?;
                }
                Ok(None) => {}
                Err(Error::Forbidden)
                    if self
                        .client()
                        .session()
                        .is_some_and(|session| session.active_team_id.is_none()) => {}
                Err(error) => return Err(error),
            }
            if !generation.is_current() || cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            self.startup_hydration.retain(|remaining| remaining != &id);
        }
        Ok(())
    }
}

#[cfg(all(test, unix))]
#[path = "startup_opened_tests.rs"]
mod tests;
