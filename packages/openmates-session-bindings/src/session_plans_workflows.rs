//! Typed Plan authoring and Workflow execution through the shared Rust services.

use super::work::Request;
use super::*;
use openmates_sdk::work::{
    PlanCreate, PlanFilters, PlanPatch, WorkflowCreate, WorkflowFilters, WorkflowPatch,
    WorkflowRunOptions, WorkflowWaitOptions,
};

impl SessionBridge {
    pub async fn plans_list(&self, filters: PlanFilters) -> Result<String> {
        self.work_transaction(Request::PlansList(filters)).await
    }
    pub async fn plans_show(&self, id: String, filters: PlanFilters) -> Result<String> {
        self.work_transaction(Request::PlanShow(id, filters)).await
    }
    pub async fn plans_create(&self, input: PlanCreate, filters: PlanFilters) -> Result<String> {
        self.work_transaction(Request::PlanCreate(Box::new(input), filters))
            .await
    }
    pub async fn plans_update(
        &self,
        id: String,
        input: PlanPatch,
        filters: PlanFilters,
    ) -> Result<String> {
        self.work_transaction(Request::PlanUpdate(id, Box::new(input), filters))
            .await
    }
    pub async fn plans_delete(
        &self,
        id: String,
        confirmed: bool,
        filters: PlanFilters,
    ) -> Result<String> {
        self.work_transaction(Request::PlanDelete(id, confirmed, filters))
            .await
    }
    pub async fn workflows_list(&self, filters: WorkflowFilters) -> Result<String> {
        self.work_transaction(Request::WorkflowsList(filters)).await
    }
    pub async fn workflows_show(&self, id: String, filters: WorkflowFilters) -> Result<String> {
        self.work_transaction(Request::WorkflowShow(id, filters))
            .await
    }
    pub async fn workflows_create(
        &self,
        input: WorkflowCreate,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowCreate(Box::new(input), filters))
            .await
    }
    pub async fn workflows_update(
        &self,
        id: String,
        input: WorkflowPatch,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowUpdate(id, input, filters))
            .await
    }
    pub async fn workflows_delete(
        &self,
        id: String,
        confirmed: bool,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowDelete(id, confirmed, filters))
            .await
    }
    pub async fn workflows_run(
        &self,
        id: String,
        input: WorkflowRunOptions,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowRun(id, input, filters))
            .await
    }
    pub async fn workflows_run_detail(
        &self,
        id: String,
        run: String,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowRunDetail(id, run, filters))
            .await
    }
    pub async fn workflows_wait(
        &self,
        id: String,
        run: String,
        options: WorkflowWaitOptions,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowWait(id, run, options, filters))
            .await
    }
    pub async fn workflows_cancel_run(
        &self,
        id: String,
        run: String,
        filters: WorkflowFilters,
    ) -> Result<String> {
        self.work_transaction(Request::WorkflowCancelRun(id, run, filters))
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn unsupported_team_cancel_preserves_personal_observer_without_dispatch() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        let bridge = SessionBridge::new(&json!({"api_url":endpoint,"app_url":null,"enhanced_privacy":false,"allow_private_operations":false}).to_string()).unwrap_or_else(|_|panic!("construct"));
        let run = "55555555-5555-4555-8555-555555555555".to_owned();
        let cancel = CancellationToken::new();
        bridge.state.workflow_waits.lock().unwrap().insert(
            "synthetic-observer".into(),
            WorkflowWait {
                run: run.clone(),
                cancel: cancel.clone(),
            },
        );
        let result = bridge
            .workflows_cancel_run(
                "44444444-4444-4444-8444-444444444444".into(),
                run,
                WorkflowFilters {
                    team_id: Some("88888888-8888-4888-8888-888888888888".into()),
                    ..Default::default()
                },
            )
            .await;
        assert_eq!(result.err().map(|e| e.code), Some("unavailable"));
        assert!(!cancel.is_cancelled());
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(30), listener.accept())
                .await
                .is_err()
        );
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
    }
}
