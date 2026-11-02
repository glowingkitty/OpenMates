"""Typed DTOs and errors for the native session SDK.

Pure data declarations shared by ``session_client`` and its facades; no native
or network access happens here. ``session_client`` re-exports every name.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict


class SessionChatDetailsLatestHistory(TypedDict):
    kind: Literal["latest"]
    limit: int


class SessionChatDetailsFullHistory(TypedDict):
    kind: Literal["full"]


SessionChatDetailsHistory = SessionChatDetailsLatestHistory | SessionChatDetailsFullHistory


class SessionChatDetailsOptions(TypedDict, total=False):
    """Core wire options; omitted values request latest limit30 and stored PII text."""
    history: SessionChatDetailsHistory
    content_mode: Literal["stored", "page_local"]


class _OptionalChatDetailsMetadata(TypedDict, total=False):
    participantUserHashes: list[str]
    activeFocusId: str


class SessionChatDetailsMetadata(_OptionalChatDetailsMetadata):
    id: str
    chatVisibility: Literal["personal", "team", "direct"]
    shortId: str
    slug: str | None
    title: str | None
    summary: str | None
    createdAt: int | float | None
    updatedAt: int | float | None
    category: str | None
    mateName: str | None
    parentId: str | None
    isSubChat: bool
    isHiddenCandidate: bool
    isHidden: bool
    pinned: bool
    hasDraft: bool
    draftPreview: str | None
    metadataUpdatedAt: int


class _OptionalChatDetailsMessage(TypedDict, total=False):
    piiMappings: Any


class SessionChatDetailsMessage(_OptionalChatDetailsMessage):
    id: str
    clientMessageId: str
    chatId: str
    role: str
    content: str
    senderName: str | None
    hashedSenderUserId: str | None
    category: str | None
    modelName: str | None
    createdAt: int | float
    embedIds: list[str]


class _OptionalChatDetailsRead(TypedDict, total=False):
    has_more_before: bool


class SessionChatDetailsRead(_OptionalChatDetailsRead):
    """Exact shared rich result; optional keys retain omission/empty semantics."""
    chat: SessionChatDetailsMetadata
    messages: list[SessionChatDetailsMessage]
    follow_up_suggestions: list[str]


class _OptionalFullChatMetadata(TypedDict, total=False):
    slug: str


class SessionFullChatRead(_OptionalFullChatMetadata):
    """Full read with optional authentic encrypted slug; never a cache ACK."""
    id: str
    title: str
    category: str
    messages: list[dict[str, Any]]


class SessionMessageWindowCursor(TypedDict):
    """Non-authorizing selector valid only for its current native Client context."""
    chatId: str
    scope: str
    createdAt: int
    messageId: str


class SessionMessageWindowOptions(TypedDict, total=False):
    direction: Literal["latest", "before", "after", "around"]
    limit: int
    cursor: SessionMessageWindowCursor
    anchorMessageId: str
    respectCompressionBoundary: bool


class SessionMessageWindow(TypedDict):
    chat: dict[str, Any]
    hasMoreBefore: bool
    hasMoreAfter: bool
    anchorFound: bool
    startCursor: SessionMessageWindowCursor | None
    endCursor: SessionMessageWindowCursor | None
    serverMessageCount: int | None
    messagesVersion: int | None
    oversizedMessage: bool
    oversizedMessageCursor: SessionMessageWindowCursor | None
    payloadBytes: int
    piiRestoration: Literal["page_local"]
    historyComplete: Literal[False]


class SessionSavedChatReadMetadata(TypedDict):
    id: str
    title: str | None
    summary: str | None
    category: str | None
    slug: str | None
    activeFocusId: str | None
    createdAt: int | None
    lastEditedAt: int | None
    metadataUpdatedAt: int | None
    parentId: str | None
    isSubChat: bool | None
    isHidden: bool | None
    pinned: bool | None
    chatVisibility: str | None
    participantUserHashes: list[str] | None
    hasDraft: bool | None
    followUpSuggestions: list[str] | None


class SessionSavedChatMessageMetadata(TypedDict):
    id: str
    storageId: str | None
    sourceMessageId: str | None
    clientMessageId: str | None
    chatId: str
    createdAt: int
    rawStatus: str | None
    senderName: str | None
    category: str | None
    modelName: str | None
    thinkingSignature: str | None
    hasThinking: bool | None
    thinkingTokenCount: int | None
    hashedUserId: str | None
    userMessageId: str | None
    keyVersion: int | None
    queueRevision: int | None
    queueMode: str | None
    queueDispatchStatus: str | None
    queueDispatchMode: str | None
    queueDispatchTaskId: str | None
    embedIds: list[str] | None


class SessionSavedChatReadOptions(TypedDict, total=False):
    limit: int
    before: SessionMessageWindowCursor
    after: SessionMessageWindowCursor
    anchorMessageId: str
    maxPages: int
    respectCompressionBoundary: bool
    contentMode: Literal["stored", "page_local"]


class SessionSavedChatRead(TypedDict):
    chat: dict[str, Any]
    hasMoreBefore: bool
    hasMoreAfter: bool
    anchorFound: bool
    startCursor: SessionMessageWindowCursor | None
    endCursor: SessionMessageWindowCursor | None
    serverMessageCount: int | None
    messagesVersion: int | None
    oversizedMessage: bool
    oversizedMessageCursor: SessionMessageWindowCursor | None
    payloadBytes: int
    piiRestoration: Literal["stored", "page_local"]
    historyComplete: Literal[False]
    chatMetadata: SessionSavedChatReadMetadata
    messageMetadata: list[SessionSavedChatMessageMetadata]

    piiMappingsByMessageId: dict[str, list[Any]]
    contentMode: Literal["stored", "page_local"]
    pagesRead: int

class _SavedChatExactRequired(TypedDict):
    cursor: SessionMessageWindowCursor


class SessionSavedChatExactOptions(_SavedChatExactRequired, total=False):
    contentMode: Literal["stored", "page_local"]


class SessionSavedChatExactMessage(TypedDict):
    message: dict[str, Any]
    piiMappings: list[Any] | None
    contentMode: Literal["stored", "page_local"]
    piiRestoration: Literal["stored", "page_local"]
    payloadBytes: int
    historyComplete: Literal[False]
    chatMetadata: SessionSavedChatReadMetadata
    messageMetadata: SessionSavedChatMessageMetadata


class SessionWorkScope(TypedDict, total=False):
    personal: bool
    team_id: str


class SessionTaskFilters(SessionWorkScope, total=False):
    status: str
    chat_id: str
    project_id: str
    plan_id: str
    labels: list[str]
    external_chat: dict[str, str]
    priority: int
    limit: int


class SessionProjectFilters(SessionWorkScope, total=False):
    include_archived: bool


class SessionProjectUnlinkInput(TypedDict):
    item_type: Literal["embed", "chat", "workflow"]
    target_id: str
    confirmed: bool


class _TaskRequired(TypedDict):
    title: str


class SessionTaskCreate(_TaskRequired, total=False):
    description: str
    slug: str
    task_id: str
    assign: str
    labels: list[str]
    status: str
    priority: int
    due_at: int
    primary_chat_id: str
    linked_project_ids: list[str]
    plan_id: str
    external_chat: dict[str, str]
    position: int


class SessionTaskPatch(TypedDict, total=False):
    title: str
    description: str
    slug: str
    assign: str
    labels: list[str]
    add_labels: list[str]
    remove_labels: list[str]
    status: str
    priority: int
    due_at: int | None
    primary_chat_id: str | None
    linked_project_ids: list[str]
    plan_id: str | None
    external_chat: dict[str, str] | None


class _ProjectRequired(TypedDict):
    name: str


class SessionProjectCreate(_ProjectRequired, total=False):
    description: str
    icon: str
    color: str
    slug: str
    pinned: bool
    project_id: str
    write_mode: Literal["always_ask", "apply_and_show"]
    chat_organization_only: bool
    default_focus: dict[str, str]


class SessionProjectPatch(TypedDict, total=False):
    name: str
    description: str
    icon: str
    color: str
    slug: str
    pinned: bool
    archived: bool
    last_opened_at: int


class SessionDraftRecord(TypedDict):
    """Rust-owned Personal draft; no cache-freshness or durable-publish receipt."""
    chat_id: str
    encrypted_draft_md: str
    encrypted_draft_preview: str | None
    draft_v: int
    markdown: str
    preview: str | None


class SessionWorkflowFileSyncOptions(TypedDict, total=False):
    source_chat: str
    approved_paths: list[str]

class _WorkflowFileSaveRequired(TypedDict):
    project_id: str
    status: Literal["saved","pending","conflict","failed"]

class SessionWorkflowFileSaveStatus(_WorkflowFileSaveRequired, total=False):
    error: str


class SessionPlanFilters(SessionWorkScope, total=False):
    status: str
    chat_id: str
    project_id: str
    active_only: bool


class SessionPlanEvidence(TypedDict, total=False):
    kind: Literal["url", "file", "embed"]
    url: str
    path: str
    embed_id: str
    start_line: int
    end_line: int


class SessionPlanFlow(TypedDict, total=False):
    flow_id: str
    title: str
    actor: str | None
    steps: list[dict[str, Any]]
    expected_outcome: str
    linked_task_ids: list[str]
    linked_criterion_ids: list[str]


class _PlanRequired(TypedDict):
    title: str
    goal: str
    linked_project_ids: list[str]


class SessionPlanCreate(_PlanRequired, total=False):
    slug: str
    plan_id: str
    scope_in: str
    scope_out: str
    user_flows: list[SessionPlanFlow]
    assumptions: str
    open_questions: str
    constraints: str
    decisions: str
    risks: str
    reference_patterns: str
    context: str
    status: str
    primary_chat_id: str
    planner_focus_id: str


class SessionPlanPatch(TypedDict, total=False):
    title: str
    goal: str
    linked_project_ids: list[str]
    slug: str
    scope_in: str
    scope_out: str
    user_flows: list[SessionPlanFlow]
    assumptions: str
    open_questions: str
    constraints: str
    decisions: str
    risks: str
    reference_patterns: str
    context: str
    status: str
    primary_chat_id: str | None
    planner_focus_id: str | None


class SessionWorkflowFilters(SessionWorkScope, total=False):
    app_id: str
    offset: int
    limit: int


class SessionWorkflowNode(TypedDict, total=False):
    id: str
    type: str
    title: str
    config: dict[str, Any]
    input_mapping: dict[str, Any]
    ui: dict[str, Any]


class SessionWorkflowGraph(TypedDict, total=False):
    version: int
    trigger_node_id: str
    nodes: list[SessionWorkflowNode]
    edges: list[dict[str, str]]
    variables: dict[str, Any]
    limits: dict[str, Any]
    ui_layout: dict[str, Any]


class _WorkflowRequired(TypedDict):
    title: str
    graph: SessionWorkflowGraph


class SessionWorkflowCreate(_WorkflowRequired, total=False):
    description: str
    category: str
    icon: str
    enabled: bool
    run_content_retention: Literal["last_5", "none"]
    lifecycle: Literal["persisted", "temporary", "chat_embed"]
    source: str
    slug: str
    source_chat_id: str
    created_by_assistant: bool
    auto_delete_at: int


class SessionWorkflowPatch(TypedDict, total=False):
    title: str
    graph: SessionWorkflowGraph
    description: str
    category: str
    icon: str
    enabled: bool
    run_content_retention: Literal["last_5", "none"]
    slug: str
    version: int


class _RunRequired(TypedDict):
    idempotency_key: str


class SessionWorkflowRunOptions(_RunRequired, total=False):
    mode: Literal["manual", "test"]
    input: dict[str, Any]
    source_chat_id: str
    message_destination_overrides: dict[str, str]
    return_outputs: dict[str, dict[str, str]]


class SessionWorkflowWaitOptions(TypedDict, total=False):
    timeout_ms: int
    poll_interval_ms: int
    sync_interval_ms: int


class SessionAnonymousOptions(TypedDict, total=False):
    pii_detection: bool
    response_timeout_ms: int


class _AnonymousOutcomeRequired(TypedDict):
    chat: dict[str, Any]
    status: Literal["completed"]
    chatId: str
    messageId: str | None
    userMessageId: str
    assistant: str


class SessionAnonymousOutcome(_AnonymousOutcomeRequired, total=False):
    category: str | None
    modelName: str | None
    mateName: str | None
    followUpSuggestions: list[str]
    suggestedFollowupMessage: str | None
    taskProposals: list[Any]
    taskUpdateProposals: list[Any]
    taskEvents: list[Any]
    pendingTaskUpdateJobs: list[Any]
    subChatEvents: list[Any]
    appSettingsMemoryRequests: list[Any]
    tokenUsage: dict[str, Any] | None
    promptBudget: dict[str, Any] | None


class SessionClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SessionSettingsReadError(SessionClientError):
    def __init__(self, code: str, message: str, http_status: int | None):
        self.http_status = http_status
        super().__init__(code, message)


def _failure(error: Exception) -> SessionClientError:
    if isinstance(error, SessionClientError):
        return error
    try:
        value = json.loads(str(error))
        if isinstance(value.get("code"), str) and isinstance(value.get("message"), str):
            if "http_status" in value and (value["http_status"] is None or (type(value["http_status"]) is int and 100 <= value["http_status"] <= 999)):
                return SessionSettingsReadError(value["code"], value["message"], value["http_status"])
            return SessionClientError(value["code"], value["message"])
    except (ValueError, TypeError, AttributeError):
        pass
    return SessionClientError("native_failure", "The native session operation failed.")
