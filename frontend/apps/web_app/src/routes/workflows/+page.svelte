<!--
  Workflows route for the authenticated web app.
  Provides the V1 server-backed workflow list, Shortcuts-style detail/editor
  shell, example workflow creation, manual runs, and run history.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Workflows/WorkflowStore.swift
  - apple/OpenMates/Sources/Features/Workflows/WorkflowViews.swift
-->

<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto, pushState, replaceState } from '$app/navigation';
	import {
		Header,
		Settings,
		NotificationStack,
		WorkspaceHomeShell,
		WorkflowDetailPage,
		WorkflowGraphRenderer,
		WorkflowSidebar,
		authStore,
		focusTrap,
		initialize,
		notificationStore,
		panelState,
		featureAvailabilityStore,
		initializeFeatureAvailability,
		consumeProjectWorkflowTarget,
		projectWorkflowAssociationWarning,
		saveWorkflowToProjectTarget,
		upsertWorkflowTemplateProjection,
		workflowWorkspaceStore,
		type ProjectCreationTarget
	} from '@repo/ui';
	import { text } from '@repo/ui';
	import {
		dailyWeatherNewsGraph,
		weeklyEventsGraph,
		hourlyApartmentsGraph
	} from '@repo/ui/components/workflows/workflowExamples.ts';
	import {
		workflowIcon,
		workflowGraphReady
	} from '@repo/ui/components/workflows/workflowBuilder.ts';
	import WorkspacePromptComposer from '@repo/ui/components/workspace/WorkspacePromptComposer.svelte';
	import WorkflowPendingPreview from '@repo/ui/components/workflows/WorkflowPendingPreview.svelte';
	import WorkflowBindingReview from '@repo/ui/components/workflows/WorkflowBindingReview.svelte';
	import { downloadWorkflowFile, isWorkflowFileName, readWorkflowFile } from '@repo/ui/services/workflowFileService';
	import { committedWorkflows, getWorkflowInstruction, stopWorkflowInstruction, streamWorkflowInstruction, undoWorkflowInstruction, workflowNodeChanges, type WorkflowAcceptedPreview, type WorkflowInputChange, type WorkflowInputSession, type WorkflowInputStreamEvent } from '@repo/ui/services/workflowInputService';
	import WorkflowRunHistory from '@repo/ui/components/workflows/WorkflowRunHistory.svelte';
	import WorkflowVersionHistory from '@repo/ui/components/workflows/WorkflowVersionHistory.svelte';
	import { userProfile } from '@repo/ui/stores/userProfile.ts';
	import { WorkflowApiError } from '@repo/ui/stores/workflowWorkspaceStore.ts';
	import type { WorkflowBindingRequirement, WorkflowDetail, WorkflowGraph, WorkflowRun, WorkflowSummary } from '@repo/ui';

	import type { DailyInspiration } from '@repo/ui/stores/dailyInspirationStore.ts';

	type WorkflowContinueItem = {
		id: string;
		title: string;
		summary?: string | null;
		badge?: string | null;
		category?: string | null;
		appId?: string | null;
		icon?: string | null;
		source?: 'recent' | 'example';
	};

	type WorkflowTab = 'details' | 'runs';

	type WorkflowHashState = {
		workflowId: string | null;
		tab: WorkflowTab;
		runId: string | null;
	};
	type WorkflowAudioRecording = {
		liveTranscript?: string;
		realtime?: {
			transcription: Promise<{ transcript: string }>;
			correction: Promise<{ useCorrected: boolean; correctionSkipped?: boolean; transcriptCorrected?: string }>;
		};
	};

	const WORKFLOWS_ROUTE = '/';
	const WORKFLOW_ID_HASH_PARAM = 'workflow-id';
	const WORKFLOW_TAB_HASH_PARAM = 'workflow-tab';
	const WORKFLOW_RUN_ID_HASH_PARAM = 'run-id';

	let workflows = $derived<WorkflowSummary[]>($workflowWorkspaceStore.workflows);
	let selectedWorkflow = $derived<WorkflowDetail | null>($workflowWorkspaceStore.selectedWorkflow);
	let runs = $derived<WorkflowRun[]>($workflowWorkspaceStore.runs);
	let saving = $state(false);
	let routeError = $state<string | null>(null);
	let authoringReminder = $state<string | null>(null);
	let error = $derived(routeError ?? $workflowWorkspaceStore.error);
	let runContentRetention = $state<'last_5' | 'none'>('last_5');
	let selectedRunContentRetention = $state<'last_5' | 'none'>('last_5');
	let editorTitle = $state('');
	let editorDescription = $state('');
	let editorGraph = $state<WorkflowGraph | null>(null);
	let editorDirty = $state(false);
	let workflowGraphRef = $state<WorkflowGraphRenderer | null>(null);
	let editorHasPendingDraft = $state(false);
	let identityResetSignal = $state(0);
	let hydratedEditorWorkflow: WorkflowDetail | null = null;
	let verifyingMissingWorkflow: { id: string; generation: number } | null = null;
	let pendingNavigation = $state<{ action: () => void | Promise<void> } | null>(null);
	let showAllWorkflows = $state(false);
	let workflowClosing = $state(false);
	let workflowOpening = $state(false);

	// Keep the pane mounted for the same 320ms CSS motion used by UnifiedEmbedFullscreen.
	function fullscreenWorkflowMotion() {
		return { duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320 };
	}
	let workflowInputText = $state('');
	let editorInstruction = $state('');
	let voiceTarget = $state<'home' | 'editor' | null>(null);
	let newWorkflowIds = $state<string[]>([]);
	let aiChange = $state<WorkflowInputChange | null>(null);
	let aiSession = $state<WorkflowInputSession | null>(null);
	let createdAiSession = $state<WorkflowInputSession | null>(null);
	let createdAiWorkflowIds = $state<string[]>([]);
	let creationSessionRestored = false;
	let undoConflict = $state(false);
	let authoringAssumptions = $state<string[]>([]);
	let authoringAssumptionsWorkflowId = $state<string | null>(null);
	let pendingSaveSessionId = $state<string | null>(null);
	let pendingSaveMessage = $state<string | null>(null);
	let pendingPreviewWorkflow = $state<WorkflowDetail | null>(null);
	let streamPreviewWorkflows = $state<WorkflowDetail[]>([]);
	let provisionalFullscreen = $state<WorkflowDetail | null>(null);
	let provisionalDismissed = false;
	let authoringScope: { operation: 'create' | 'update' | 'mixed'; workflowCount: number } | null = null;
	let authoringPhase = $state<'planning' | 'validating' | 'retrying_node' | 'saving' | null>(null);
	let acceptedNodeCounts = $state<Record<string, number>>({});
	let stopRequested = $state(false);
	let partialNotice = $state<string | null>(null);
	let partialWorkflowIds = $state<string[]>([]);
	let streamController: AbortController | null = null;
	let interruptedSubmission: { instruction: string; workflowId?: string; key: string } | null = null;
	let pendingPreviewTargetId = $state<string | null>(null);
	let pendingResumeStarted = false;
	let activeEditorPreview = $derived(streamPreviewWorkflows.find(item => item.id === pendingPreviewTargetId) ?? pendingPreviewWorkflow);
	let landingPreviewWorkflows = $derived(pendingPreviewTargetId === null && !provisionalFullscreen ? streamPreviewWorkflows : []);
	let routeAlive = true;
	let observedWorkflowGeneration = $state(workflowWorkspaceStore.getGeneration());
	let workflowHashState = $state<WorkflowHashState>({
		workflowId: null,
		tab: 'details',
		runId: null
	});
	let blankCreatorOpen = $state(false);
	let blankWorkflowTitle = $state('');
	let projectWorkflowTarget = $state<ProjectCreationTarget | null>(null);
	let lastStartedRunId = $state<string | null>(null);
	let workflowImportInput = $state<HTMLInputElement | null>(null);
	let draggingWorkflowFile = $state(false);

	let recentWorkflows = $derived.by(() => {
		const sorted = [...workflows].sort((left, right) => (right.updated_at ?? 0) - (left.updated_at ?? 0));
		const recent = sorted.slice(0, 6);
		return [...recent, ...sorted.filter(item => newWorkflowIds.includes(item.id) && !recent.some(other => other.id === item.id))];
	});
	let workflowStarterItems: WorkflowContinueItem[] = [
		{
			id: 'starter-rain',
			title: 'Daily weather and news',
			summary: 'Rain timing and the latest articles in a new chat',
			badge: 'Starter',
			category: 'weather',
			appId: 'weather',
			icon: 'cloud-rain',
			source: 'example'
		},
		{
			id: 'starter-news',
			title: 'Weekly AI events',
			summary: 'Discover AI events for the upcoming week',
			badge: 'Starter',
			category: 'technology',
			appId: 'news',
			icon: 'calendar-days',
			source: 'example'
		},
		{
			id: 'starter-apartments',
			title: 'Find new apartments every hour',
			summary: 'Only previously undelivered listings',
			badge: 'Starter',
			category: 'productivity',
			appId: 'home',
			icon: 'house',
			source: 'example'
		}
	];
	let recentWorkflowContinueItems = $derived<WorkflowContinueItem[]>(
		recentWorkflows.map(workflowSummaryToContinueItem)
	);
	let allWorkflowContinueItems = $derived<WorkflowContinueItem[]>(
		[...workflows]
			.sort((left, right) => (right.updated_at ?? 0) - (left.updated_at ?? 0))
			.map(workflowSummaryToContinueItem)
	);
	let workflowLandingItems = $derived<WorkflowContinueItem[]>([
		...recentWorkflowContinueItems,
		...workflowStarterItems
	]);
	let workflowGreetingName = $derived($userProfile.username?.trim() || 'there');
	let isManageView = $derived(!!workflowHashState.workflowId);
	let isRunsView = $derived(workflowHashState.tab === 'runs');
	let selectedRunId = $derived(workflowHashState.runId);
	let requestedWorkflowId = $derived(workflowHashState.workflowId);

	let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
	let routeReady = $derived($authStore.isInitialized && featureAvailabilityLoaded);
	let workflowsEnabled = $derived(
		!featureAvailabilityLoaded ||
			($featureAvailabilityStore.disabledById?.['platform:workflows'] !== true &&
				$featureAvailabilityStore.disabledById !== null)
	);
	let canLoadWorkflows = $derived(routeReady && $authStore.isAuthenticated && workflowsEnabled);
	let canRenderWorkflowData = $derived(routeReady && $authStore.isAuthenticated);
	let showManageView = $derived(canRenderWorkflowData && (isManageView || !!provisionalFullscreen));
	let visibleWorkflowGreetingName = $derived(
		canRenderWorkflowData ? workflowGreetingName : 'there'
	);
	let visibleWorkflowLandingItems = $derived(canRenderWorkflowData ? workflowLandingItems : []);
	let editorActivationReady = $derived(
		editorGraph && selectedWorkflow?.binding_requirements?.every(requirement => selectedWorkflow?.completed_binding_requirements?.some(completed => completed.type === requirement.type && completed.node_id === requirement.node_id)) !== false
			? workflowGraphReady(editorGraph, { requireSchedule: true }) : false
	);
	let savedRunReady = $derived(
		selectedWorkflow && selectedWorkflow.binding_requirements?.every(requirement => selectedWorkflow?.completed_binding_requirements?.some(completed => completed.type === requirement.type && completed.node_id === requirement.node_id)) !== false
			? workflowGraphReady(selectedWorkflow.graph) : false
	);

	async function importWorkflowFile(file: File): Promise<void> {
		if (!canLoadWorkflows || saving || pendingSaveSessionId) return;
		if (!isWorkflowFileName(file.name)) {
			routeError = $text('workflows.builder.file_import_choose');
			return;
		}
		saving = true;
		routeError = null;
		try {
			const workflowDocument = await readWorkflowFile(file);
			if (!workflowDocument) throw new Error($text('workflows.builder.file_import_choose'));
			const imported = await workflowWorkspaceStore.importWorkflowFile(workflowDocument);
			await selectWorkflow(imported.id);
			openWorkflowDetails(imported.id);
			notificationStore.success($text('workflows.builder.file_import_success'));
		} catch (importError) {
			routeError = importError instanceof Error ? importError.message : $text('workflows.builder.file_import_failed');
		} finally {
			saving = false;
		}
	}

	function handleWorkflowFileDrop(event: DragEvent): void {
		draggingWorkflowFile = false;
		const file = event.dataTransfer?.files?.[0];
		if (!file) return;
		event.preventDefault();
		void importWorkflowFile(file);
	}

	async function confirmBinding(requirement: WorkflowBindingRequirement): Promise<void> {
		if (!selectedWorkflow || editorDirty || saving || workflowGraphRef?.hasPendingDraft()) return;
		const node = selectedWorkflow.graph.nodes.find(item => item.id === requirement.node_id);
		const input: WorkflowBindingRequirement & { chat_id?: string; new_chat?: boolean } = { ...requirement };
		if (requirement.type === 'chat_destination') {
			const chatId = String(node?.config?.chat_id ?? '').trim();
			if (chatId) input.chat_id = chatId;
			else if (String(node?.config?.title ?? '').trim()) input.new_chat = true;
			else { routeError = $text('workflows.builder.file_binding_chat_missing'); return; }
		}
		saving = true;
		routeError = null;
		try {
			const updated = await workflowWorkspaceStore.completeBindingRequirement(selectedWorkflow.id, input);
			resetEditor(updated);
		} catch (bindingError) {
			routeError = bindingError instanceof Error ? bindingError.message : $text('workflows.builder.file_binding_failed');
		} finally {
			saving = false;
		}
	}
	$effect(() => {
		const previewCount = landingPreviewWorkflows.length;
		if (!previewCount) return;
		void tick().then(() => {
			const previews = document.querySelectorAll('[data-testid="workflow-ai-pending-preview"]');
			previews[previewCount - 1]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
		});
	});
	let hasTimeTrigger = $derived(
		editorGraph?.nodes.some((node) => node.type === 'schedule_trigger') ?? false
	);

	onMount(() => {
		routeAlive = true;
		if (window.location.pathname !== '/') {
			const legacyState = readWorkflowHashState(window.location.hash);
			const canonicalHash = workflowStateHash(
				legacyState.workflowId,
				legacyState.tab,
				legacyState.runId
			);
			void goto(`${WORKFLOWS_ROUTE}${canonicalHash}`, { replaceState: true });
			return;
		}

		projectWorkflowTarget = consumeProjectWorkflowTarget();
		if (projectWorkflowTarget) blankCreatorOpen = true;
		syncWorkflowHashFromLocation();
		window.addEventListener('hashchange', syncWorkflowHashFromLocation);
		window.addEventListener('popstate', syncWorkflowHashFromLocation);
		const refreshVisibleWorkflow = () => {
			if (!routeAlive || !canLoadWorkflows || editorDirty || saving || workflowGraphRef?.hasPendingDraft()) return;
			void workflowWorkspaceStore.loadWorkflows().catch(() => undefined);
			const selectedId = $workflowWorkspaceStore.selectedWorkflowId;
			if (selectedId) void workflowWorkspaceStore.selectWorkflow(selectedId).catch(() => undefined);
		};
		const onVisibilityChange = () => { if (!document.hidden) refreshVisibleWorkflow(); };
		window.addEventListener('focus', refreshVisibleWorkflow);
		window.addEventListener('online', refreshVisibleWorkflow);
		document.addEventListener('visibilitychange', onVisibilityChange);
		void initializeWorkflowsRoute();

		return () => {
			routeAlive = false;
			streamController?.abort();
			window.removeEventListener('hashchange', syncWorkflowHashFromLocation);
			window.removeEventListener('popstate', syncWorkflowHashFromLocation);
			window.removeEventListener('focus', refreshVisibleWorkflow);
			window.removeEventListener('online', refreshVisibleWorkflow);
			document.removeEventListener('visibilitychange', onVisibilityChange);
		};
	});

	function stripHashPrefix(hash: string): string {
		if (!hash) return '';
		return hash.startsWith('#/') ? hash.slice(2) : hash.replace(/^#/, '');
	}

	function parseHashParams(hash: string): URLSearchParams {
		const fragment = stripHashPrefix(hash);
		if (!fragment || fragment === 'settings' || fragment.startsWith('settings/')) {
			return new URLSearchParams();
		}
		return new URLSearchParams(fragment);
	}

	function serializeHashParams(params: URLSearchParams): string {
		const pairs: string[] = [];
		params.forEach((value, key) => {
			pairs.push(
				`${encodeURIComponent(key)}=${encodeURIComponent(value).replace(/%2F/g, '/').replace(/%3A/g, ':')}`
			);
		});
		return pairs.length > 0 ? `#${pairs.join('&')}` : '';
	}

	function readWorkflowHashState(hash: string): WorkflowHashState {
		const params = parseHashParams(hash);
		const workflowId = params.get(WORKFLOW_ID_HASH_PARAM)?.trim() || null;
		const tab = params.get(WORKFLOW_TAB_HASH_PARAM) === 'runs' ? 'runs' : 'details';
		return {
			workflowId,
			tab: workflowId ? tab : 'details',
			runId:
				workflowId && tab === 'runs' ? params.get(WORKFLOW_RUN_ID_HASH_PARAM)?.trim() || null : null
		};
	}

	function syncWorkflowHashFromLocation(): void {
		const nextState = readWorkflowHashState(window.location.hash);
		if (
			(editorDirty || workflowGraphRef?.hasPendingDraft()) &&
			(nextState.workflowId !== workflowHashState.workflowId ||
				nextState.tab !== workflowHashState.tab ||
				nextState.runId !== workflowHashState.runId)
		) {
			const currentHash = workflowStateHash(
				workflowHashState.workflowId,
				workflowHashState.tab,
				workflowHashState.runId
			);
			replaceState(`${WORKFLOWS_ROUTE}${currentHash}`, {});
			requestNavigation(() =>
				setWorkflowUrlState(nextState.workflowId, nextState.tab, nextState.runId)
			);
			return;
		}
		workflowHashState = nextState;
	}

	function workflowStateHash(
		workflowId: string | null,
		tab: WorkflowTab = 'details',
		runId: string | null = null,
		baseHash = ''
	): string {
		const params = parseHashParams(baseHash);
		params.delete('workflows');
		params.delete('projects');
		params.delete('tasks');
		params.delete('project-id');
		params.delete('task-id');
		params.delete(WORKFLOW_ID_HASH_PARAM);
		params.delete(WORKFLOW_TAB_HASH_PARAM);
		params.delete(WORKFLOW_RUN_ID_HASH_PARAM);

		if (workflowId) {
			const routeParams = new URLSearchParams();
			routeParams.set(WORKFLOW_ID_HASH_PARAM, workflowId);
			routeParams.set(WORKFLOW_TAB_HASH_PARAM, tab);
			if (tab === 'runs' && runId) {
				routeParams.set(WORKFLOW_RUN_ID_HASH_PARAM, runId);
			}
			params.forEach((value, key) => routeParams.append(key, value));
			return serializeHashParams(routeParams);
		}

		const preservedHash = serializeHashParams(params);
		return `#workflows${preservedHash ? `&${preservedHash.slice(1)}` : ''}`;
	}

	function setWorkflowUrlState(
		workflowId: string | null,
		tab: WorkflowTab = 'details',
		runId: string | null = null,
		replaceHistory = false
	): void {
		const nextHash = workflowStateHash(workflowId, tab, runId, window.location.hash);
		workflowHashState = readWorkflowHashState(nextHash);
		if (window.location.pathname === WORKFLOWS_ROUTE && window.location.hash === nextHash) return;
		if (replaceHistory) {
			replaceState(`${WORKFLOWS_ROUTE}${nextHash}`, {});
		} else {
			pushState(`${WORKFLOWS_ROUTE}${nextHash}`, {});
		}
	}

	function workflowStateHref(workflowId: string, tab: WorkflowTab = 'details'): string {
		return `${WORKFLOWS_ROUTE}${workflowStateHash(workflowId, tab)}`;
	}

	function openWorkflowDetails(workflowId: string): void {
		setWorkflowUrlState(workflowId, 'details');
	}

	function openWorkflowRuns(workflowId: string, runId: string | null = null): void {
		setWorkflowUrlState(workflowId, 'runs', runId);
	}

	function openWorkflowHome(replaceHistory = false): void {
		setWorkflowUrlState(null, 'details', null, replaceHistory);
	}

	function requestNavigation(action: () => void | Promise<void>): void {
		if (editorDirty || workflowGraphRef?.hasPendingDraft()) {
			pendingNavigation = { action };
			return;
		}
		void action();
	}

	function requestWorkflowHome(): void {
		requestNavigation(openWorkflowHome);
	}

	function requestWorkflowShare(): void {
		notificationStore.info(
			$text('workflows.builder.sharing_soon'),
			4000,
			true,
			'workflow-sharing-soon'
		);
	}

	function requestWorkflowTab(tab: 'template' | 'runs'): void {
		if (!selectedWorkflow) return;
		requestNavigation(() =>
			tab === 'runs'
				? openWorkflowRuns(selectedWorkflow.id)
				: openWorkflowDetails(selectedWorkflow.id)
		);
	}

	function requestWorkflowSelection(workflowId: string): void {
		requestNavigation(async () => {
			await selectWorkflow(workflowId);
			openWorkflowDetails(workflowId);
		});
	}

	async function saveAndContinueNavigation(): Promise<void> {
		const navigation = pendingNavigation;
		if (!navigation) return;
		if (workflowGraphRef?.hasPendingDraft() && !await workflowGraphRef.savePendingDraft()) return;
		if (editorDirty) await saveSelectedWorkflow();
		if (editorDirty) return;
		identityResetSignal += 1;
		pendingNavigation = null;
		await navigation.action();
	}

	async function discardAndContinueNavigation(): Promise<void> {
		const navigation = pendingNavigation;
		if (!navigation) return;
		workflowGraphRef?.discardPendingDraft();
		undoEditorChanges();
		identityResetSignal += 1;
		pendingNavigation = null;
		await navigation.action();
	}

	async function initializeWorkflowsRoute() {
		try {
			await initialize();
			await initializeFeatureAvailability();
		} catch (initError) {
			console.error('[WorkflowsRoute] Failed to initialize:', initError);
			routeError = initError instanceof Error ? initError.message : 'Failed to load workflows.';
		}
	}

	async function selectWorkflow(workflowId: string) {
		routeError = null;
		const sameWorkflowAlreadySelected = $workflowWorkspaceStore.selectedWorkflowId === workflowId;
		if (!sameWorkflowAlreadySelected) authoringReminder = null;
		const workflow = await workflowWorkspaceStore.selectWorkflow(workflowId);
		if (sameWorkflowAlreadySelected && (editorDirty || saving || pendingSaveSessionId || streamController || workflowGraphRef?.hasPendingDraft())) return;
		const latest = $workflowWorkspaceStore.selectedWorkflow;
		const currentWorkflow = latest?.id === workflowId ? latest : workflow;
		selectedRunContentRetention = currentWorkflow.run_content_retention ?? 'last_5';
		resetEditor(currentWorkflow);
		aiChange = null;
		aiSession = null;
		undoConflict = false;
		const sessionId = localStorage.getItem(`workflow-ai-session:${workflowId}`);
		if (sessionId) {
			void getWorkflowInstruction(sessionId).then(session => {
				if (workflowHashState.workflowId !== workflowId || (session.status !== 'executed' && !(session.status === 'draft' && session.partial_reason))) return;
				if (session.partial_reason) {
					partialNotice = session.partial_warning || session.message || 'This workflow is saved with completed steps and is paused.';
					partialWorkflowIds = committedWorkflows(session).map(item => item.id);
				}
				const mutation = session.mutations?.find(item => item.target_id === workflowId);
				if (!mutation) return;
				aiSession = session;
				aiChange = session.changes?.find(item => item.workflow_id === workflowId) ?? {
					workflow_id: workflowId,
					...workflowNodeChanges(mutation.before?.graph?.nodes ?? [], mutation.after?.graph?.nodes ?? [])
				};
			}).catch(() => undefined);
		}
	}

	$effect(() => {
		if (!canLoadWorkflows) return;
		const generation = $workflowWorkspaceStore.generation;
		void workflowWorkspaceStore.loadWorkflows().catch((loadError) => {
			if (!workflowWorkspaceStore.isCurrentGeneration(generation)) return;
			console.error('[WorkflowsRoute] Failed to warm workflow cache:', loadError);
		});
	});

	$effect(() => {
		if (!canLoadWorkflows || creationSessionRestored) return;
		creationSessionRestored = true;
		const raw = sessionStorage.getItem('workflow-ai-last-batch');
		if (!raw) return;
		try {
			const saved = JSON.parse(raw) as { sessionId: string; workflowIds: string[] };
			void getWorkflowInstruction(saved.sessionId).then(session => {
				if (session.status !== 'executed' && !(session.status === 'draft' && session.partial_reason)) {
					sessionStorage.removeItem('workflow-ai-last-batch');
					return;
				}
				if (session.partial_reason) {
					partialNotice = session.partial_warning || session.message || 'This workflow is saved with completed steps and is paused.';
					partialWorkflowIds = committedWorkflows(session).map(item => item.id);
				}
				createdAiSession = session;
				newWorkflowIds = saved.workflowIds;
				createdAiWorkflowIds = saved.workflowIds;
				authoringAssumptions = session.assumptions ?? [];
				authoringAssumptionsWorkflowId = saved.workflowIds.length === 1 ? saved.workflowIds[0] : null;
			}).catch(() => sessionStorage.removeItem('workflow-ai-last-batch'));
		} catch {
			sessionStorage.removeItem('workflow-ai-last-batch');
		}
	});

	$effect(() => {
		if (!canLoadWorkflows || pendingResumeStarted) return;
		pendingResumeStarted = true;
		const raw = sessionStorage.getItem('workflow-ai-pending');
		if (!raw) return;
		try {
			const pending = JSON.parse(raw) as { sessionId: string; workflowId?: string };
			pendingSaveSessionId = pending.sessionId;
			pendingSaveMessage = $text('workflows.builder.ai_saving');
			void authorWorkflow('', pending.workflowId, pending.sessionId);
		} catch {
			sessionStorage.removeItem('workflow-ai-pending');
		}
	});

	$effect(() => {
		if (!canLoadWorkflows) return;
		const requestedId = requestedWorkflowId;
		if (!requestedId) {
			verifyingMissingWorkflow = null;
			return;
		}
		const requestedWorkflow = requestedWorkflowId
			? workflows.find((workflow) => workflow.id === requestedWorkflowId)
			: null;
		if (!requestedWorkflow && $workflowWorkspaceStore.listStatus === 'ready') {
			const generation = $workflowWorkspaceStore.generation;
			if (verifyingMissingWorkflow?.id === requestedId && verifyingMissingWorkflow.generation === generation) return;
			const verification = { id: requestedId, generation };
			verifyingMissingWorkflow = verification;
			void (async () => {
				// Let the completed list request clear its in-flight marker before forcing a new read.
				await new Promise((resolve) => setTimeout(resolve, 0));
				try {
					const refreshed = await workflowWorkspaceStore.loadWorkflows({ force: true });
					if (verifyingMissingWorkflow !== verification || !workflowWorkspaceStore.isCurrentGeneration(generation) || workflowHashState.workflowId !== requestedId) return;
					if (!refreshed.some((workflow) => workflow.id === requestedId) &&
						!$workflowWorkspaceStore.workflows.some((workflow) => workflow.id === requestedId)) openWorkflowHome(true);
				} catch (loadError) {
					if (verifyingMissingWorkflow === verification && workflowWorkspaceStore.isCurrentGeneration(generation) && workflowHashState.workflowId === requestedId) {
						verifyingMissingWorkflow = null;
						routeError = loadError instanceof Error ? loadError.message : 'Could not verify workflow link.';
						console.error('[WorkflowsRoute] Failed to verify workflow link:', loadError);
					}
				}
			})();
			return;
		}
		if (!requestedWorkflow) return;
		verifyingMissingWorkflow = null;
		if (requestedId === $workflowWorkspaceStore.selectedWorkflowId) return;
		void selectWorkflow(requestedId).catch((selectError) => {
			if (selectError instanceof WorkflowApiError && selectError.status === 404 && workflowHashState.workflowId === requestedId) {
				openWorkflowHome(true);
				return;
			}
			console.error('[WorkflowsRoute] Failed to select workflow:', selectError);
		});
	});

	$effect(() => {
		const workflow = selectedWorkflow;
		if (!workflow || hydratedEditorWorkflow === workflow || editorDirty || saving || pendingSaveSessionId || streamController || editorHasPendingDraft || workflowGraphRef?.hasPendingDraft()) return;
		selectedRunContentRetention = workflow.run_content_retention ?? 'last_5';
		resetEditor(workflow);
	});

	$effect(() => {
		const generation = $workflowWorkspaceStore.generation;
		if (!canRenderWorkflowData || generation !== observedWorkflowGeneration) {
			observedWorkflowGeneration = generation;
			routeError = null;
		}
	});

	async function createRainWorkflow() {
		await createWorkflow('Daily weather and news', rainAlertGraph(), false);
	}

	async function createNewsWorkflow() {
		await createWorkflow('Weekly AI events', newsBriefGraph(), false);
	}

	async function submitBlankWorkflow(): Promise<void> {
		const title = blankWorkflowTitle.trim();
		if (!title || saving) return;
		const created = await createWorkflow(title, blankWorkflowGraph(), false);
		if (created) closeBlankWorkflowCreator();
	}

	function closeBlankWorkflowCreator(): void {
		blankCreatorOpen = false;
		blankWorkflowTitle = '';
		projectWorkflowTarget = null;
	}

	function startWorkflowFromInspiration(inspiration: DailyInspiration) {
		if (!canRenderWorkflowData) return;
		workflowInputText = inspiration.phrase || inspiration.title || '';
	}

	async function continueWorkflowFromCard(item: { id: string }) {
		if (!canLoadWorkflows) return;
		requestWorkflowSelection(item.id);
	}

	async function startWorkflowFromCard(item: WorkflowContinueItem) {
		if (!canLoadWorkflows) return;
		if (item.id === 'starter-rain') {
			await createRainWorkflow();
		} else if (item.id === 'starter-news') {
			await createNewsWorkflow();
		} else if (item.id === 'starter-apartments') {
			await createWorkflow('Hourly apartment search', hourlyApartmentsGraph(), false);
		} else {
			await continueWorkflowFromCard(item);
		}
	}

	async function submitWorkflowInput(text: string = workflowInputText): Promise<void> {
		const instruction = text.trim();
		if (!instruction || saving || pendingSaveSessionId || !canLoadWorkflows) return;
		workflowInputText = instruction;
		await authorWorkflow(instruction);
	}

	async function stopAuthoring(): Promise<void> {
		if (!saving || stopRequested) return;
		stopRequested = true;
		pendingSaveMessage = $text('workflows.builder.ai_stopping');
		if (pendingSaveSessionId) await acknowledgeStop(pendingSaveSessionId);
	}

	async function acknowledgeStop(sessionId: string): Promise<void> {
		try {
			// Acknowledge Stop on the server before closing the event stream. GET then
			// recovers its durable partial result, including across worker processes.
			await stopWorkflowInstruction(sessionId);
			streamController?.abort();
		} catch (cause) {
			stopRequested = false;
			pendingSaveMessage = null;
			routeError = cause instanceof Error ? cause.message : 'Could not stop workflow creation.';
		}
	}

	function submitEditorInstruction(text: string): void {
		if (!selectedWorkflow || !text.trim() || pendingSaveSessionId) return;
		editorInstruction = text.trim();
		requestNavigation(() => authorWorkflow(text.trim(), selectedWorkflow.id));
	}

	async function handleWorkflowAudioRecorded(event: CustomEvent<WorkflowAudioRecording>, target: 'home' | 'editor'): Promise<void> {
		const { realtime, liveTranscript } = event.detail;
		let raw = liveTranscript?.trim() ?? '';
		const review = () => {
			if (target === 'home') workflowInputText = raw;
			else editorInstruction = raw;
			if (!raw) routeError = $text('workflows.builder.voice_transcription_failed');
		};
		if (!realtime) {
			review();
			return;
		}
		try {
			raw = (await realtime.transcription).transcript.trim() || raw;
			const corrected = await realtime.correction;
			if (corrected.correctionSkipped) {
				if (!raw) {
					review();
					return;
				}
				if (target === 'home') await submitWorkflowInput(raw);
				else submitEditorInstruction(raw);
				return;
			}
			if (!corrected.useCorrected || !corrected.transcriptCorrected?.trim()) {
				review();
				return;
			}
			if (target === 'home') await submitWorkflowInput(corrected.transcriptCorrected);
			else submitEditorInstruction(corrected.transcriptCorrected);
		} catch {
			review();
		}
	}

	function handoffWorkflowClarification(instruction: string, workflowId?: string): void {
		// Keep the exact instruction and the editor target together in the new chat.
		const target = workflowId && selectedWorkflow?.id === workflowId ? selectedWorkflow : null;
		const context = target
			? `\n\nWorkflow editor context: I was changing my existing workflow ${JSON.stringify(target.title)} (ID ${target.id}). Keep this workflow as the target. Clarify the change before carrying out any of the workflow's future search or delivery actions.`
			: '\n\nWorkflow workspace context: Clarify the workflow creation or edit before carrying out its future search or delivery actions.';
		const message = `@focus:workflows:clarify_workflows ${instruction}${context}`;
		sessionStorage.setItem('docs_auto_send', 'true');
		sessionStorage.setItem('workflow_clarification_new_chat', 'true');
		// The root page can change its hash during asynchronous startup. Retain the
		// same request for its one-time workflow handoff recovery path.
		sessionStorage.setItem('workflow_clarification_pending_message', message);
		void goto(`/#message=${encodeURIComponent(message)}`);
	}

	async function authorWorkflow(instruction: string, workflowId?: string, existingSessionId?: string): Promise<void> {
		if (saving) return;
		const before = workflowId && selectedWorkflow?.id === workflowId ? selectedWorkflow : null;
		authoringAssumptions = [];
		authoringAssumptionsWorkflowId = null;
		undoConflict = false;
		pendingPreviewWorkflow = null;
		streamPreviewWorkflows = [];
		provisionalFullscreen = workflowId ? null : initialAuthoringPreview();
		provisionalDismissed = false;
		authoringScope = null;
		authoringPhase = null;
		acceptedNodeCounts = {};
		stopRequested = false;
		partialNotice = null;
		partialWorkflowIds = [];
		pendingSaveMessage = null;
		pendingPreviewTargetId = workflowId ?? null;
		saving = true;
		routeError = null;
		const showAcceptedPreview = (event: WorkflowAcceptedPreview) => {
			if (event.graph.version !== 2) return;
			const preview: WorkflowDetail = {
				id: event.metadata.workflow_id ?? (event.operation === 'update' || event.metadata.action === 'update' ? workflowId : undefined) ?? `provisional-${event.workflow_index}`,
				title: event.metadata.title,
				description: event.metadata.description ?? null,
				category: event.metadata.category,
				icon: event.metadata.icon,
				status: 'provisional', enabled: workflows.find(item => item.id === event.metadata.workflow_id)?.enabled ?? false, current_version_id: '',
				graph: event.graph
			};
			acceptedNodeCounts = { ...acceptedNodeCounts, [preview.id]: event.accepted_node_count ?? event.graph.nodes.length };
			streamPreviewWorkflows = [...streamPreviewWorkflows.filter(item => item.id !== preview.id), preview];
			if (workflowId && preview.id === workflowId) pendingPreviewWorkflow = preview;
			if (!workflowId && !provisionalDismissed && event.workflow_index === 0 && (event.operation ?? event.metadata.action) === 'create' && ((authoringScope?.operation === 'create' && authoringScope.workflowCount === 1) || (authoringScope === null && streamPreviewWorkflows.every(item => item.id === preview.id)))) {
				provisionalFullscreen = preview;
			} else if (!workflowId) {
				provisionalFullscreen = null;
				if ((event.operation ?? event.metadata.action) === 'update' && event.metadata.workflow_id && workflows.some(item => item.id === event.metadata.workflow_id)) {
					const targetId = event.metadata.workflow_id;
					if (pendingPreviewTargetId !== targetId) {
						pendingPreviewTargetId = targetId;
						void selectWorkflow(targetId).then(() => openWorkflowDetails(targetId)).catch(cause => {
							routeError = cause instanceof Error ? cause.message : 'Could not open the workflow being updated.';
						});
					}
				}
			}
		};
		try {
			let session: WorkflowInputSession;
			if (existingSessionId) {
				session = await getWorkflowInstruction(existingSessionId);
			} else {
				const key = interruptedSubmission?.instruction === instruction && interruptedSubmission.workflowId === workflowId
					? interruptedSubmission.key : crypto.randomUUID();
				interruptedSubmission = { instruction, workflowId, key };
				const controller = new AbortController();
				streamController = controller;
				authoringPhase = 'planning';
				let startedSessionId: string | null = null;
				const onEvent = (event: WorkflowInputStreamEvent) => {
					if (!routeAlive) return;
					if (event.type === 'started') {
						startedSessionId = event.session_id;
						pendingSaveSessionId = event.session_id;
						sessionStorage.setItem('workflow-ai-pending', JSON.stringify({ sessionId: event.session_id, workflowId }));
						if (stopRequested) void acknowledgeStop(event.session_id);
					} else if (event.type === 'progress') {
						authoringPhase = event.phase;
						if (event.operation && Number.isInteger(event.workflow_count) && (event.workflow_count ?? 0) > 0) {
							authoringScope = { operation: event.operation, workflowCount: event.workflow_count! };
							if (!workflowId && (event.operation !== 'create' || event.workflow_count !== 1)) {
								provisionalFullscreen = null;
							} else if (event.operation === 'create' && event.workflow_count === 1 && !workflowId && !provisionalDismissed) {
								provisionalFullscreen = streamPreviewWorkflows.find(item => item.id === 'provisional-0') ?? provisionalFullscreen;
							}
						}
					} else if (event.type === 'preview' && event.provisional && event.validated && event.graph.version === 2) {
						showAcceptedPreview(event);
					}
				};
				try {
					session = await streamWorkflowInstruction(instruction, workflowId, onEvent, controller.signal, key);
				} catch (streamError) {
					if (!routeAlive || (controller.signal.aborted && !stopRequested)) throw streamError;
					if (controller.signal.aborted && stopRequested && startedSessionId) {
						session = await getWorkflowInstruction(startedSessionId);
					} else if (!startedSessionId) {
						// Reuse the same key: the server may have accepted the first request.
						try {
							session = await streamWorkflowInstruction(instruction, workflowId, onEvent, controller.signal, key);
						} catch (retryError) {
							if (!startedSessionId) throw retryError;
							session = await getWorkflowInstruction(startedSessionId);
						}
					} else {
						session = await getWorkflowInstruction(startedSessionId);
					}
				}
				streamController = null;
			}
			let pendingChecks = 0;
			while (session.status === 'running' || session.status === 'queued' || session.status === 'saving') {
				pendingSaveSessionId = session.session_id;
				pendingSaveMessage = stopRequested ? 'Stopping after the current step...' : session.message || $text('workflows.builder.ai_saving');
				pendingPreviewWorkflow = session.preview_workflow ?? pendingPreviewWorkflow;
				if (session.preview_workflows?.length) streamPreviewWorkflows = session.preview_workflows;
				for (const preview of session.partial_previews ?? []) showAcceptedPreview(preview);
				if (!stopRequested) authoringPhase = 'saving';
				pendingPreviewTargetId = workflowId ?? null;
				authoringAssumptions = session.assumptions ?? authoringAssumptions;
				sessionStorage.setItem('workflow-ai-pending', JSON.stringify({ sessionId: session.session_id, workflowId }));
				await new Promise(resolve => setTimeout(resolve, pendingChecks++ < 2 ? 500 : 1500));
				if (!routeAlive) return;
				session = await getWorkflowInstruction(session.session_id);
			}
			pendingSaveSessionId = null;
			pendingSaveMessage = null;
			pendingPreviewWorkflow = null;
			streamPreviewWorkflows = [];
			authoringPhase = null;
			pendingPreviewTargetId = null;
			sessionStorage.removeItem('workflow-ai-pending');
			interruptedSubmission = null;
			stopRequested = false;
			if (session.status === 'needs_clarification') {
				if (instruction) handoffWorkflowClarification(instruction, workflowId);
				else routeError = session.message || 'Please clarify the workflow request in chat.';
				return;
			}
			const isPartial = session.status === 'draft' && !!session.partial_reason;
			if (session.status === 'draft' && !isPartial) {
				if (!session.workflow) {
					routeError = session.message || $text('workflows.builder.ai_draft_unsaved');
					return;
				}
				await workflowWorkspaceStore.loadWorkflows({ force: true });
				await selectWorkflow(session.workflow.id);
				openWorkflowDetails(session.workflow.id);
				workflowInputText = '';
				return;
			}
			if (session.status !== 'executed' && !isPartial) {
				routeError = session.error || session.message || $text('workflows.builder.ai_failed');
				return;
			}
			const committed = committedWorkflows(session);
			if (!committed.length) {
				routeError = $text('workflows.builder.ai_missing_result');
				return;
			}
			if (isPartial) {
				partialNotice = session.partial_warning || session.message || 'This workflow is saved with the completed steps and is paused. Add the missing steps manually or ask for a specific update.';
				partialWorkflowIds = committed.map(item => item.id);
			}
			authoringAssumptions = session.assumptions ?? [];
			const previouslyKnownIds = new Set(workflows.map(item => item.id));
			await workflowWorkspaceStore.loadWorkflows({ force: true });
			const createdIds = new Set(session.mutations?.filter(item => item.type === 'create_workflow').map(item => item.target_id) ?? []);
			const created = committed.filter(item => createdIds.has(item.id) || (!session.mutations?.length && item.id !== workflowId && !previouslyKnownIds.has(item.id)));
			if (created.length) {
				createdAiSession = session;
				createdAiWorkflowIds = created.map(item => item.id);
				sessionStorage.setItem('workflow-ai-last-batch', JSON.stringify({ sessionId: session.session_id, workflowIds: created.map(item => item.id) }));
				newWorkflowIds = [...new Set([...created.map(item => item.id), ...newWorkflowIds])];
				showAllWorkflows = false;
				if (created.length === 1 && committed.length === 1) {
					authoringAssumptionsWorkflowId = created[0].id;
					await selectWorkflow(created[0].id);
					openWorkflowDetails(created[0].id);
				} else {
					openWorkflowHome();
				}
			}
			const updatedIds = new Set(session.mutations?.filter(item => item.type === 'update_workflow').map(item => item.target_id) ?? []);
			if (workflowId) updatedIds.add(workflowId);
			const updatedWorkflows = committed.filter(item => updatedIds.has(item.id));
			for (const updated of updatedWorkflows) {
				workflowWorkspaceStore.upsertWorkflow(updated);
				localStorage.setItem(`workflow-ai-session:${updated.id}`, session.session_id);
			}
			if (updatedWorkflows.length === 1 && created.length === 0) {
				const updated = updatedWorkflows[0];
				if (!workflowId) {
					await selectWorkflow(updated.id);
					openWorkflowDetails(updated.id);
				}
				const mutation = session.mutations?.find(item => item.target_id === updated.id);
				resetEditor(updated);
				identityResetSignal += 1;
				aiChange = session.changes?.find(change => change.workflow_id === updated.id) ?? {
					workflow_id: updated.id,
					...workflowNodeChanges(before?.graph.nodes ?? mutation?.before?.graph?.nodes ?? [], updated.graph.nodes)
				};
				aiSession = session;
				authoringAssumptionsWorkflowId = updated.id;
			} else if (updatedWorkflows.length > 1) {
				openWorkflowHome();
			}
			workflowInputText = '';
			editorInstruction = '';
		} catch (cause) {
			if (!(cause instanceof DOMException && cause.name === 'AbortError')) routeError = cause instanceof Error ? cause.message : $text('workflows.builder.ai_failed');
		} finally {
			streamController = null;
			streamPreviewWorkflows = [];
			provisionalFullscreen = null;
			authoringScope = null;
			pendingPreviewWorkflow = null;
			authoringPhase = null;
			saving = false;
		}
	}

	async function undoAiChanges(): Promise<void> {
		if (!selectedWorkflow || saving) return;
		const sessionId = aiSession?.session_id || localStorage.getItem(`workflow-ai-session:${selectedWorkflow.id}`);
		if (!sessionId) return;
		saving = true;
		routeError = null;
		try {
			const result = await undoWorkflowInstruction(sessionId);
			if (result.error || result.status !== 'undone') {
				routeError = result.error || $text('workflows.builder.ai_undo_conflict');
				undoConflict = result.error_code === 'WORKFLOW_INPUT_UNDO_CONFLICT';
				return;
			}
			localStorage.removeItem(`workflow-ai-session:${selectedWorkflow.id}`);
			aiSession = null;
			aiChange = null;
			undoConflict = false;
			await workflowWorkspaceStore.loadWorkflows({ force: true });
			const restored = await workflowWorkspaceStore.selectWorkflow(selectedWorkflow.id, { force: true });
			resetEditor(restored);
			identityResetSignal += 1;
		} catch (cause) {
			routeError = cause instanceof Error ? cause.message : $text('workflows.builder.ai_undo_failed');
		} finally {
			saving = false;
		}
	}

	async function undoCreatedAiChanges(): Promise<void> {
		if (!createdAiSession?.undo_available || saving) return;
		saving = true;
		routeError = null;
		try {
			const result = await undoWorkflowInstruction(createdAiSession.session_id);
			if (result.error || result.status !== 'undone') {
				routeError = result.error || $text('workflows.builder.ai_undo_failed');
				return;
			}
			createdAiSession = null;
			const undoingOpenWorkflow = selectedWorkflow && createdAiWorkflowIds.includes(selectedWorkflow.id);
			sessionStorage.removeItem('workflow-ai-last-batch');
			newWorkflowIds = newWorkflowIds.filter(id => !createdAiWorkflowIds.includes(id));
			createdAiWorkflowIds = [];
			authoringAssumptions = [];
			authoringAssumptionsWorkflowId = null;
			await workflowWorkspaceStore.loadWorkflows({ force: true });
			if (undoingOpenWorkflow) openWorkflowHome();
		} catch (cause) {
			routeError = cause instanceof Error ? cause.message : $text('workflows.builder.ai_undo_failed');
		} finally {
			saving = false;
		}
	}

	function resumePendingSave(): void {
		if (!pendingSaveSessionId || saving) return;
		const raw = sessionStorage.getItem('workflow-ai-pending');
		if (!raw) return;
		try {
			const pending = JSON.parse(raw) as { sessionId: string; workflowId?: string };
			void authorWorkflow('', pending.workflowId, pending.sessionId);
		} catch {
			sessionStorage.removeItem('workflow-ai-pending');
			pendingSaveSessionId = null;
			pendingSaveMessage = null;
		}
	}

	function showWorkflowSearchUnavailable(): void {
		notificationStore.info('Workflow search is coming soon.', 4000, true, 'workflows-search');
	}

	function showAllWorkflowCards(): void {
		showAllWorkflows = true;
	}

	function showRecentWorkflowCards(): void {
		showAllWorkflows = false;
	}

	function workflowSummaryToContinueItem(workflow: WorkflowSummary): WorkflowContinueItem {
		return {
			id: workflow.id,
			title: workflow.title,
			summary: `${workflow.trigger_summary ?? 'Manual'} - ${retentionLabel(workflow.run_content_retention)}`,
			badge: newWorkflowIds.includes(workflow.id) ? 'New' : workflow.enabled ? 'Enabled' : 'Paused',
			category: workflow.category ?? 'general_knowledge',
			icon: workflowIcon(workflow.title, workflow.icon),
			source: 'recent'
		};
	}

	async function createWorkflow(
		title: string,
		graph: WorkflowGraph,
		enabled: boolean
	): Promise<boolean> {
		if (!canLoadWorkflows || saving) return false;
		const workflowProjectTarget = projectWorkflowTarget;
		saving = true;
		routeError = null;
		try {
			const workflow = await workflowWorkspaceStore.createWorkflow({
				title,
				graph,
				enabled,
				runContentRetention
			});
			// Keep the selected location for a retry when workflow creation itself fails.
			projectWorkflowTarget = null;
			let associationWarning: string | null = null;
			if (workflowProjectTarget) {
				try {
					await saveWorkflowToProjectTarget(workflowProjectTarget, workflow.id, workflow.title);
				} catch (associationError) {
					associationWarning = projectWorkflowAssociationWarning(
						workflowProjectTarget,
						associationError
					);
				}
			}
			await maintainTemplateProjection(workflow);
			await selectWorkflow(workflow.id);
			openWorkflowDetails(workflow.id);
			if (associationWarning) routeError = associationWarning;
			return true;
		} catch (createError) {
			routeError =
				createError instanceof Error ? createError.message : 'Failed to create workflow.';
			return false;
		} finally {
			saving = false;
		}
	}

	async function setSelectedWorkflowEnabled(enabled: boolean) {
		if (!selectedWorkflow) return;
		saving = true;
		routeError = null;
		try {
			const workflow = await workflowWorkspaceStore.setWorkflowEnabled(
				selectedWorkflow.id,
				enabled
			);
			resetEditor(workflow);
			clearAiReview(workflow.id);
		} catch (saveError) {
			routeError = saveError instanceof Error ? saveError.message : 'Failed to update workflow.';
		} finally {
			saving = false;
		}
	}

	async function runSelectedWorkflow() {
		if (!selectedWorkflow || saving || !savedRunReady) return;
		const workflowId = selectedWorkflow.id;
		saving = true;
		routeError = null;
		try {
			const run = await workflowWorkspaceStore.runWorkflow(workflowId);
			lastStartedRunId = run.id;
			openWorkflowRuns(workflowId, run.id);
		} catch (runError) {
			routeError = runError instanceof Error ? runError.message : 'Failed to run workflow.';
		} finally {
			saving = false;
		}
	}

	async function deleteSelectedWorkflow() {
		if (
			!selectedWorkflow ||
			!window.confirm(`Delete “${selectedWorkflow.title}”? This cannot be undone.`)
		)
			return;
		saving = true;
		routeError = null;
		try {
			await workflowWorkspaceStore.deleteWorkflow(selectedWorkflow.id);
			openWorkflowHome();
		} catch (deleteError) {
			routeError =
				deleteError instanceof Error ? deleteError.message : 'Failed to delete workflow.';
		} finally {
			saving = false;
		}
	}

	async function saveSelectedWorkflow() {
		if (!selectedWorkflow || !editorGraph) return;
		saving = true;
		routeError = null;
		try {
			const workflow = await workflowWorkspaceStore.patchWorkflow(selectedWorkflow.id, {
				title: editorTitle.trim() || selectedWorkflow.title,
				description: editorDescription.trim(),
				graph: editorGraph,
				run_content_retention: selectedRunContentRetention
			});
			resetEditor(workflow);
			clearAiReview(workflow.id);
			saving = false;
			await maintainTemplateProjection(workflow);
		} catch (saveError) {
			routeError = saveError instanceof Error ? saveError.message : 'Failed to save workflow.';
		} finally {
			saving = false;
		}
	}

	async function maintainTemplateProjection(workflow: WorkflowDetail): Promise<void> {
		try {
			await upsertWorkflowTemplateProjection(workflow);
		} catch (projectionError) {
			const message =
				projectionError instanceof Error
					? projectionError.message
					: 'Could not update the encrypted workflow template projection.';
			routeError = `Workflow saved, but its shareable template was not updated: ${message}`;
		}
	}

	async function handleWorkflowVersionRestored(workflow: WorkflowDetail): Promise<void> {
		resetEditor(workflow);
		identityResetSignal += 1;
		clearAiReview(workflow.id);
		await maintainTemplateProjection(workflow);
	}

	function rainAlertGraph(): WorkflowGraph {
		return dailyWeatherNewsGraph();
	}

	function blankWorkflowGraph(): WorkflowGraph {
		return {
			version: 2,
			trigger_node_id: null,
			nodes: [],
			edges: []
		};
	}

	function initialAuthoringPreview(): WorkflowDetail {
		return {
			id: 'provisional-0', title: $text('workflows.builder.processing'), description: null,
			category: 'general_knowledge', status: 'provisional', enabled: false,
			current_version_id: '', graph: blankWorkflowGraph()
		};
	}

	function newsBriefGraph(): WorkflowGraph {
		return weeklyEventsGraph();
	}

	function resetEditor(workflow: WorkflowDetail) {
		editorTitle = workflow.title;
		editorDescription = workflow.description ?? '';
		editorGraph = cloneGraph(workflow.graph);
		editorDirty = false;
		hydratedEditorWorkflow = workflow;
	}

	function clearAiReview(workflowId: string): void {
		aiChange = null;
		aiSession = null;
		undoConflict = false;
		localStorage.removeItem(`workflow-ai-session:${workflowId}`);
	}

	function undoEditorChanges() {
		if (selectedWorkflow) resetEditor(selectedWorkflow);
	}

	function cloneGraph(graph: WorkflowGraph): WorkflowGraph {
		return JSON.parse(JSON.stringify(graph)) as WorkflowGraph;
	}

	function retentionLabel(value: 'last_5' | 'none' | undefined): string {
		return value === 'none' ? 'No durable run content' : 'Keep latest 5 encrypted runs';
	}

	async function saveNodeGraph(graph: WorkflowGraph): Promise<void> {
		if (!selectedWorkflow) throw new Error('Workflow unavailable');
		saving = true;
		routeError = null;
		authoringReminder = null;
		try {
			const workflow = await workflowWorkspaceStore.patchWorkflow(selectedWorkflow.id, {
				graph,
				title: editorTitle.trim() || selectedWorkflow.title,
				description: editorDescription,
				icon: workflowIcon(editorTitle, selectedWorkflow.icon, graph)
			});
			authoringReminder =
				workflow.authoring_warnings?.map((warning) => warning.message).join(' ') || null;
			resetEditor(workflow);
			identityResetSignal += 1;
			clearAiReview(workflow.id);
			await maintainTemplateProjection(workflow);
		} catch (error) {
			routeError = error instanceof Error ? error.message : 'Failed to save workflow';
			throw error;
		} finally {
			saving = false;
		}
	}

	async function updateWorkflowIdentity(title: string, description: string): Promise<void> {
		if (!selectedWorkflow) return;
		saving = true;
		try {
			const workflow = await workflowWorkspaceStore.patchWorkflow(selectedWorkflow.id, {
				title: title.trim(),
				description,
				graph: editorGraph ?? selectedWorkflow.graph,
				run_content_retention: selectedRunContentRetention
			});
			resetEditor(workflow);
			clearAiReview(workflow.id);
			await maintainTemplateProjection(workflow);
		} finally {
			saving = false;
		}
	}

	function updateEditorGraph(graph: WorkflowGraph): void {
		editorGraph = graph;
		editorDirty = true;
	}
</script>

{#if routeReady && !workflowsEnabled}
	<Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
	<main class="workflows-route-state" data-testid="workflows-feature-disabled">
		<h1>Workflows unavailable</h1>
		<p>Workflows are disabled on this server.</p>
	</main>
{:else if routeReady && !$authStore.isAuthenticated}
	<Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
	<main class="workflows-route-state" data-testid="workflows-auth-required">
		<h1>Workflows</h1>
		<p>Please log in to create, manage, and run server-side workflows.</p>
	</main>
{:else}
	<div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
		<Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
		<div class="chat-container workflows-container" class:menu-open={$panelState.isSettingsOpen}>
			<div class="workflow-sidebar-shell" class:drawer-open={$panelState.isActivityHistoryOpen}>
				<WorkflowSidebar
					onSelect={(workflow) => {
						void continueWorkflowFromCard(workflow);
						panelState.closeChats();
					}}
				/>
			</div>
			<main
				class="active-chat-container workflows-start"
				class:management-view={showManageView}
				data-testid="workflows-page"
			>
				{#if error}
					<div class="error-banner" data-testid="workflows-error">{error}</div>
				{/if}

				{#if !showManageView}
					<WorkspaceHomeShell
						surface="workflows"
						testId="workflows-start-screen"
						heading={`Hey ${visibleWorkflowGreetingName}!`}
						subtitle="What do you want to automate next?"
						actionItems={visibleWorkflowLandingItems}
						actionItemsTestId="workflow-mixed-row"
						itemTestId="workflow-landing-card"
						showReportIssue
						showAllMode={showAllWorkflows}
						contentSlotVisible={streamPreviewWorkflows.length > 0 || (partialNotice !== null && partialWorkflowIds.length > 1) || (!!pendingSaveSessionId && !!pendingPreviewWorkflow && pendingPreviewTargetId === null)}
						showAllLabel={workflows.length > 0 ? 'Show all' : ''}
						showAllTestId="workflows-show-all"
						allItems={allWorkflowContinueItems}
						allItemsViewTestId="all-workflows-view"
						allItemsGridTestId="all-workflows-grid"
						allItemsToolbarTestId="workflows-all-toolbar"
						allItemTestId="workflow-landing-card"
						backTestId="workflows-back-to-recent"
						searchTestId="workflows-search"
						onShowAll={workflows.length > 0 ? showAllWorkflowCards : undefined}
						onBackToRecent={showRecentWorkflowCards}
						onSearchAll={showWorkflowSearchUnavailable}
						onContinueItem={continueWorkflowFromCard}
						onActionItem={startWorkflowFromCard}
						onAllItem={continueWorkflowFromCard}
						onStartInspiration={startWorkflowFromInspiration}
					>
						{#if partialNotice && partialWorkflowIds.length > 1}
							<p class="workflow-ai-partial-warning" data-testid="workflow-ai-partial-warning" role="status">{partialNotice}</p>
						{/if}
						{#each landingPreviewWorkflows as preview (preview.id)}
							<WorkflowPendingPreview workflow={preview} mode="landing" phase={authoringPhase ?? 'saving'} acceptedNodeCount={acceptedNodeCounts[preview.id] ?? 0} isNew={!workflows.some(item => item.id === preview.id)} changes={$workflowWorkspaceStore.detailsById[preview.id] ? workflowNodeChanges($workflowWorkspaceStore.detailsById[preview.id].graph.nodes, preview.graph.nodes) : null}/>
						{/each}
						{#if !streamPreviewWorkflows.length && pendingSaveSessionId && pendingPreviewWorkflow && pendingPreviewTargetId === null}
							<WorkflowPendingPreview workflow={pendingPreviewWorkflow} mode="landing" isNew={!workflows.some(item => item.id === pendingPreviewWorkflow?.id)}/>
						{/if}
						<svelte:fragment slot="composer">
							<input bind:this={workflowImportInput} type="file" accept=".workflow.yml" data-testid="workflow-import-input" onchange={(event) => { const input = event.currentTarget; const file = input.files?.[0]; if (file) void importWorkflowFile(file); input.value = ''; }} hidden />
							<div class="workflow-import-dropzone" class:dragging={draggingWorkflowFile} role="group" aria-label={$text('workflows.builder.file_import_group')} data-testid="workflow-import-dropzone" ondragover={(event) => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); draggingWorkflowFile = true; } }} ondragleave={() => { draggingWorkflowFile = false; }} ondrop={handleWorkflowFileDrop}>
							<WorkspacePromptComposer
								surface="workflows"
								bind:value={workflowInputText}
								placeholder={$text('workflows.builder.new_workflow_placeholder')}
								submitLabel="Create workflow"
								submittingLabel="Creating..."
								disabled={saving || !!pendingSaveSessionId || !canRenderWorkflowData}
								submitting={saving}
								testId="workflow-input-composer"
								inputTestId="workflow-input-textarea"
								submitTestId="workflow-input-submit"
								micTestId="workflow-input-mic"
								onSubmit={submitWorkflowInput}
								onMicClick={() => { voiceTarget = 'home'; }}
								fileImport={{ label: $text('workflows.builder.file_import_button'), testId: 'workflow-import-button', onClick: () => workflowImportInput?.click() }}
								recording={voiceTarget === 'home'}
								onAudioRecorded={(event) => handleWorkflowAudioRecorded(event, 'home')}
								onRecordingClose={() => { voiceTarget = null; }}
							/>
							{#if draggingWorkflowFile}<span class="workflow-import-hint" role="status">{$text('workflows.builder.file_import_drop_hint')}</span>{/if}
							</div>
							{#if pendingSaveSessionId || authoringPhase}<div class="workflow-ai-pending" data-testid="workflow-ai-pending" role="status"><span>{pendingSaveMessage || (authoringPhase === 'planning' ? 'Planning workflow...' : authoringPhase === 'retrying_node' ? 'Correcting this step...' : authoringPhase === 'validating' ? 'Validating workflow...' : $text('workflows.builder.ai_saving'))}</span>{#if pendingSaveSessionId && saving}<button type="button" data-testid="workflow-ai-stop" disabled={stopRequested} onclick={() => void stopAuthoring()}>{stopRequested ? 'Stopping...' : 'Stop'}</button>{/if}{#if pendingSaveSessionId && !saving}<button type="button" onclick={resumePendingSave}>{$text('workflows.builder.ai_check_status')}</button>{/if}</div>{/if}
							{#if createdAiWorkflowIds.length > 1 && authoringAssumptions.length}<p class="workflow-ai-assumptions" data-testid="workflow-ai-assumptions" role="status">{authoringAssumptions.join(' ')}</p>{/if}
						</svelte:fragment>
					</WorkspaceHomeShell>
				{/if}

				{#if showManageView}
					<section
						class="workflow-management"
						class:opening={workflowOpening}
						class:closing={workflowClosing}
						class:composer-docked={!!provisionalFullscreen || (!!selectedWorkflow && !isRunsView && !!editorGraph)}
						data-testid="workflow-management"
						transition:fullscreenWorkflowMotion
						onintrostart={() => {
							workflowClosing = false;
							workflowOpening = true;
						}}
						onintroend={() => (workflowOpening = false)}
						onoutrostart={() => {
							workflowOpening = false;
							workflowClosing = true;
						}}
					>
						<div class="management-grid">
							<section class="workflow-detail" data-testid="workflow-detail">
								{#if provisionalFullscreen}
									<WorkflowDetailPage
										title={provisionalFullscreen.title}
										description={provisionalFullscreen.description ?? ''}
										category={provisionalFullscreen.category ?? 'general_knowledge'}
										icon={workflowIcon(provisionalFullscreen.title, provisionalFullscreen.icon, provisionalFullscreen.graph)}
										enabled={false} canEnable={false} canRun={false} saving={true} provisional
										activeTab="template"
										onTabChange={() => undefined} onToggleEnabled={() => undefined}
										onRunWorkflow={() => undefined} onDeleteWorkflow={() => undefined}
										onOpenHome={() => { provisionalDismissed = true; provisionalFullscreen = null; }}
										onOpenShare={() => undefined} onExport={() => undefined}
										onOpenRuns={() => undefined} runsHref=""
										onUpdateIdentity={async () => undefined} onDraftIdentity={() => undefined}
									/>
									<div id="tabpanel-template" data-testid="workflow-template-panel" role="tabpanel" aria-label="Workflow template">
										<div data-testid="workflow-editor">
											<div class="workflow-ai-pending" data-testid="workflow-ai-processing" role="status">{pendingSaveMessage || (authoringPhase === 'saving' ? $text('workflows.builder.ai_preview_saving') : $text('workflows.builder.processing'))}</div>
											<div class="workflow-authoring-info" data-testid="workflow-authoring-info" role="status">
												{#if (acceptedNodeCounts[provisionalFullscreen.id] ?? 0) > 0}<p data-testid="workflow-ai-accepted-nodes">{$text(acceptedNodeCounts[provisionalFullscreen.id] === 1 ? 'workflows.builder.ai_validated_step' : 'workflows.builder.ai_validated_steps', { values: { count: acceptedNodeCounts[provisionalFullscreen.id] } })}</p>{/if}
												<p>{$text('workflows.builder.ai_preview_pending')}</p>
											</div>
											<div data-testid="workflow-ai-pending-preview" data-disabled="true" data-save-status={authoringPhase ?? 'saving'}>
												<WorkflowGraphRenderer graph={provisionalFullscreen.graph} readOnly onChange={() => undefined} onSave={null}/>
											</div>
										</div>
									</div>
								{:else if selectedWorkflow}
									{#key `${selectedWorkflow.id}:${identityResetSignal}`}
									<WorkflowDetailPage
										title={editorTitle || selectedWorkflow.title}
										description={editorDescription}
										category={selectedWorkflow.category ?? 'general_knowledge'}
										icon={workflowIcon(
											selectedWorkflow.title,
											selectedWorkflow.icon,
											editorGraph ?? undefined
										)}
										createdAt={selectedWorkflow.created_at}
										nextRunAt={selectedWorkflow.next_run_at}
										enabled={selectedWorkflow.enabled}
										canEnable={editorActivationReady && !editorDirty}
										canRun={savedRunReady}
										{lastStartedRunId}
										activeTab={isRunsView ? 'runs' : 'template'}
										{saving}
										onTabChange={requestWorkflowTab}
										onToggleEnabled={() => setSelectedWorkflowEnabled(!selectedWorkflow?.enabled)}
										onUpdateIdentity={updateWorkflowIdentity}
										onDraftIdentity={(title, description) => {
										editorTitle = title;
										editorDescription = description;
										editorDirty = true;
									}}
										onRunWorkflow={runSelectedWorkflow}
										onDeleteWorkflow={deleteSelectedWorkflow}
										onOpenHome={requestWorkflowHome}
										onOpenShare={requestWorkflowShare}
										onExport={() => { if (!selectedWorkflow) return; try { downloadWorkflowFile(selectedWorkflow); } catch (exportError) { routeError = exportError instanceof Error ? exportError.message : $text('workflows.builder.file_export_failed'); } }}
										onOpenRuns={() => requestWorkflowTab('runs')}
										runsHref={workflowStateHref(selectedWorkflow.id, 'runs')}
									/>
									{/key}
									{#if !isRunsView && selectedWorkflow.binding_requirements?.length}
										<WorkflowBindingReview requirements={selectedWorkflow.binding_requirements} completed={selectedWorkflow.completed_binding_requirements ?? []} graph={editorGraph ?? selectedWorkflow.graph} {saving} hasUnsavedChanges={editorDirty || !!workflowGraphRef?.hasPendingDraft()} onEdit={(nodeId) => workflowGraphRef?.openNodeEditor(nodeId)} onConfirm={confirmBinding} />
									{/if}

									{#if isRunsView}
										<WorkflowRunHistory
											workflow={selectedWorkflow}
											{runs}
											{selectedRunId}
											onSelectRun={(runId) => openWorkflowRuns(selectedWorkflow.id, runId)}
											editorHref={workflowStateHref(selectedWorkflow.id, 'details')}
											onOpenEditor={() => openWorkflowDetails(selectedWorkflow.id)}
										/>
									{:else}
										<div
											id="tabpanel-template"
											data-testid="workflow-template-panel"
											role="tabpanel"
											aria-label="Workflow template"
										>
											<WorkflowVersionHistory
												workflow={selectedWorkflow}
												disabled={saving}
												onRequestNavigation={requestNavigation}
												onRestored={handleWorkflowVersionRestored}
											>
												{#if editorGraph}
													<div data-testid="workflow-editor">
													{#if partialNotice && partialWorkflowIds.includes(selectedWorkflow.id)}<p class="workflow-ai-partial-warning" data-testid="workflow-ai-partial-warning" role="status">{partialNotice}</p>{/if}
													{#if authoringReminder || (authoringAssumptionsWorkflowId === selectedWorkflow.id && authoringAssumptions.length) || createdAiWorkflowIds.includes(selectedWorkflow.id)}
														<div class="workflow-authoring-info" data-testid="workflow-authoring-info" role="status">
															{#if createdAiWorkflowIds.includes(selectedWorkflow.id)}<p>{$text('workflows.builder.ai_created_disabled')}</p>{/if}
															{#if authoringReminder}<p data-testid="workflow-authoring-reminder">{authoringReminder}</p>{/if}
															{#if authoringAssumptionsWorkflowId === selectedWorkflow.id}{#each authoringAssumptions as assumption}<p>{assumption}</p>{/each}{/if}
															{#if createdAiWorkflowIds.includes(selectedWorkflow.id) && createdAiSession?.undo_available}<button type="button" data-testid="workflow-ai-created-undo" disabled={saving} onclick={() => void undoCreatedAiChanges()}>{$text('workflows.builder.ai_undo')}</button>{/if}
														</div>
													{/if}
											{#if aiChange && !activeEditorPreview && aiChange.workflow_id === selectedWorkflow.id}
														<div class="workflow-ai-changes" data-testid="workflow-ai-changes" role="status">
															<strong>{$text('workflows.builder.ai_changes_saved')}</strong>
															{#if aiChange.removed_nodes.length}<p>{$text('workflows.builder.ai_removed')} {aiChange.removed_nodes.map(node => node.title).join(', ')}</p>{/if}
															{#if aiChange.added_node_ids.length}<p>{aiChange.added_node_ids.length} {$text('workflows.builder.ai_added_nodes')}</p>{/if}
															{#if aiChange.edited_node_ids.length}<p>{aiChange.edited_node_ids.length} {$text('workflows.builder.ai_edited_nodes')}</p>{/if}
															<button type="button" data-testid="workflow-ai-undo" disabled={saving || !aiSession?.undo_available} onclick={() => void undoAiChanges()}>{$text('workflows.builder.ai_undo')}</button>
															{#if undoConflict}<button type="button" data-testid="workflow-ai-open-history" onclick={() => document.querySelector<HTMLButtonElement>('[data-testid="workflow-version-selector"]')?.click()}>{$text('workflows.version_history.title')}</button>{/if}
														</div>
													{/if}
											{#if activeEditorPreview && pendingPreviewTargetId === selectedWorkflow.id}
												<WorkflowPendingPreview workflow={activeEditorPreview} mode="editor" phase={authoringPhase ?? 'saving'} acceptedNodeCount={acceptedNodeCounts[activeEditorPreview.id] ?? 0} changes={workflowNodeChanges(selectedWorkflow.graph.nodes, activeEditorPreview.graph.nodes)}/>
													{:else}
													<WorkflowGraphRenderer
														bind:this={workflowGraphRef}
														graph={editorGraph}
														aiAddedNodeIds={aiChange?.workflow_id === selectedWorkflow.id ? aiChange.added_node_ids : []}
														aiEditedNodeIds={aiChange?.workflow_id === selectedWorkflow.id ? aiChange.edited_node_ids : []}
															workflowId={selectedWorkflow.id}
																onChange={updateEditorGraph}
																onSave={saveNodeGraph}
																onDraftStateChange={(hasDraft) => { editorHasPendingDraft = hasDraft; }}
																/>
													{/if}
											{#if hasTimeTrigger && !activeEditorPreview}
															<div class="workflow-test-now-row">
																<button
																	type="button"
																	class="workflow-test-now"
																	data-testid="workflow-template-test-now"
																	disabled={saving || editorDirty || !savedRunReady}
																	onclick={() => void runSelectedWorkflow()}
																>
																	<span class="workflow-icon icon-play size-20" aria-hidden="true"></span>
																	{$text('workflows.builder.test_now')}
																</button>
															</div>
														{/if}
													</div>
												{/if}
											</WorkflowVersionHistory>
										</div>
									{/if}
								{:else}
									<div class="empty-detail">
										<h2>Build your first workflow</h2>
										<p>Choose a starter workflow to create a durable server-side automation.</p>
									</div>
								{/if}
							</section>
						</div>
						{#if provisionalFullscreen}
							<div class="workflow-ai-composer" data-testid="workflow-ai-editor-composer">
								<WorkspacePromptComposer surface="workflows" bind:value={editorInstruction}
									placeholder={$text('workflows.builder.ai_edit_placeholder')} submitLabel={$text('workflows.builder.ai_edit_submit')} submittingLabel={$text('workflows.builder.ai_edit_submitting')}
									disabled={true} submitting={true} testId="workflow-ai-edit-composer" inputTestId="workflow-ai-edit-textarea"
									submitTestId="workflow-ai-edit-submit" micTestId="workflow-ai-edit-mic" onSubmit={() => undefined}
									onMicClick={() => undefined} recording={false}
									onAudioRecorded={() => undefined} onRecordingClose={() => undefined}/>
									{#if saving}<div class="workflow-ai-pending" data-testid="workflow-ai-pending" role="status"><span>{pendingSaveMessage || $text('workflows.builder.processing')}</span><button type="button" data-testid="workflow-ai-stop" disabled={stopRequested} onclick={() => void stopAuthoring()}>{stopRequested ? $text('workflows.builder.ai_stopping') : $text('workflows.builder.stop')}</button></div>{/if}
							</div>
						{:else if selectedWorkflow && !isRunsView && editorGraph}
							<div class="workflow-ai-composer" data-testid="workflow-ai-editor-composer">
								<WorkspacePromptComposer surface="workflows" bind:value={editorInstruction}
									placeholder={$text('workflows.builder.ai_edit_placeholder')} submitLabel={$text('workflows.builder.ai_edit_submit')} submittingLabel={$text('workflows.builder.ai_edit_submitting')}
									disabled={saving || !!pendingSaveSessionId} submitting={saving} testId="workflow-ai-edit-composer" inputTestId="workflow-ai-edit-textarea"
									submitTestId="workflow-ai-edit-submit" micTestId="workflow-ai-edit-mic" onSubmit={submitEditorInstruction}
									onMicClick={() => { voiceTarget = 'editor'; }} recording={voiceTarget === 'editor'}
									onAudioRecorded={(event) => handleWorkflowAudioRecorded(event, 'editor')}
									onRecordingClose={() => { voiceTarget = null; }}/>
								{#if pendingSaveSessionId || authoringPhase}<div class="workflow-ai-pending" data-testid="workflow-ai-pending" role="status"><span>{pendingSaveMessage || (authoringPhase === 'planning' ? 'Planning workflow...' : authoringPhase === 'retrying_node' ? 'Correcting this step...' : authoringPhase === 'validating' ? 'Validating workflow...' : $text('workflows.builder.ai_saving'))}</span>{#if pendingSaveSessionId && saving}<button type="button" data-testid="workflow-ai-stop" disabled={stopRequested} onclick={() => void stopAuthoring()}>{stopRequested ? 'Stopping...' : 'Stop'}</button>{/if}{#if pendingSaveSessionId && !saving}<button type="button" onclick={resumePendingSave}>{$text('workflows.builder.ai_check_status')}</button>{/if}</div>{/if}
							</div>
						{/if}
					</section>
				{/if}

				{#if pendingNavigation}
					<div
						class="unsaved-guard-backdrop"
						data-testid="workflow-unsaved-guard"
						role="presentation"
					>
						<div
							class="unsaved-guard"
							role="dialog"
							aria-modal="true"
							aria-labelledby="workflow-unsaved-title"
							use:focusTrap={{ onEscape: () => (pendingNavigation = null) }}
						>
							<h2 id="workflow-unsaved-title">Save your changes?</h2>
							<p>This Workflow has unsaved Template changes.</p>
							<div>
								<button
									type="button"
									data-testid="workflow-guard-stay"
									onclick={() => (pendingNavigation = null)}>Stay</button
								>
								<button
									type="button"
									data-testid="workflow-guard-discard"
									onclick={() => void discardAndContinueNavigation()}>Discard</button
								>
								<button
									type="button"
									class="primary"
									data-testid="workflow-guard-save"
									disabled={saving}
									onclick={() => void saveAndContinueNavigation()}>Save</button
								>
							</div>
						</div>
					</div>
				{/if}

				{#if blankCreatorOpen}
					<div
						class="blank-creator-backdrop"
						data-testid="workflow-blank-creator"
						role="presentation"
					>
						<div
							class="blank-creator"
							role="dialog"
							aria-modal="true"
							aria-labelledby="blank-workflow-title"
							use:focusTrap={{ onEscape: closeBlankWorkflowCreator }}
						>
							<form
								onsubmit={(event) => {
									event.preventDefault();
									void submitBlankWorkflow();
								}}
							>
								<h2 id="blank-workflow-title">Start a blank Workflow</h2>
								<p>Name it now, then add a time trigger and the steps it should perform.</p>
								{#if projectWorkflowTarget}
									<p data-testid="workflow-project-target">
										Save to {projectWorkflowTarget.projectName}{projectWorkflowTarget.folderPath
											? ` / ${projectWorkflowTarget.folderPath}`
											: ''}
									</p>
								{/if}
								<label
									><span>Workflow name</span><input
										data-testid="workflow-blank-title-input"
										bind:value={blankWorkflowTitle}
									/></label
								>
								<div>
									<button type="button" onclick={closeBlankWorkflowCreator}>Cancel</button>
									<button
										type="submit"
										class="primary"
										data-testid="workflow-blank-create"
										disabled={saving || !blankWorkflowTitle.trim()}
										>{saving ? 'Creating...' : 'Create'}</button
									>
								</div>
							</form>
						</div>
					</div>
				{/if}
			</main>
			<div class="settings-wrapper">
				<Settings isLoggedIn={$authStore.isAuthenticated} />
			</div>
		</div>
	</div>
{/if}

<NotificationStack />

<style>
	.workflow-ai-composer{position:relative;z-index:var(--z-index-raised-2);flex:none;box-sizing:border-box;width:100%;margin:0;padding:12px 1rem max(12px,env(safe-area-inset-bottom));background:var(--color-grey-10);box-shadow:0 -8px 24px color-mix(in srgb,var(--color-grey-100) 9%,transparent)}
	.workflow-import-dropzone{display:grid;justify-items:center;gap:.4rem;width:100%;border:2px dashed transparent;border-radius:var(--radius-5)}.workflow-import-dropzone.dragging{border-color:var(--color-button-primary);background:var(--color-grey-10)}.workflow-import-hint{font-size:var(--font-size-small);color:var(--color-font-secondary)}
	.workflow-ai-assumptions{max-width:42rem;margin:.75rem auto;text-align:center;color:var(--color-font-secondary);font-size:var(--font-size-small)}
	.workflow-ai-partial-warning{max-width:56rem;margin:.75rem auto;padding:.75rem 1rem;border:1px solid var(--color-warning, var(--color-button-primary));border-radius:.75rem;background:var(--color-grey-10);color:var(--color-font-primary)}
	.workflow-ai-pending{display:flex;justify-content:center;align-items:center;gap:.75rem;max-width:42rem;margin:.75rem auto;color:var(--color-font-secondary)}
	.workflow-ai-pending button{border:1px solid var(--color-button-primary);border-radius:.7rem;padding:.35rem .7rem;background:transparent;color:var(--color-primary);font:inherit;cursor:pointer}
	.workflow-ai-changes{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:1rem 1.25rem;border:1px solid var(--color-button-primary);border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary)}
	.workflow-authoring-info{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:.75rem 1rem;border-radius:var(--radius-8,20px);color:var(--color-font-secondary);background:var(--color-grey-10);font-size:var(--font-size-small,.875rem)}
	.workflow-authoring-info p{margin:.25rem 0}
	.workflow-authoring-info button{margin-top:.5rem;border:0;border-radius:.7rem;padding:.5rem .8rem;background:var(--color-button-primary);color:var(--color-font-button);font:inherit;cursor:pointer}
	.workflow-ai-changes p{margin:.45rem 0}
	.workflow-ai-changes button{margin-top:.5rem;border:0;border-radius:.7rem;padding:.55rem .9rem;background:var(--color-button-primary);color:var(--color-font-button);font:inherit;cursor:pointer}
	.workflows-route-state {
		min-height: calc(100vh - 90px);
		display: grid;
		place-content: center;
		gap: var(--spacing-8, 16px);
		padding: var(--spacing-20, 40px);
		text-align: center;
		color: var(--color-font-primary);
	}

	.main-content {
		container: main-content / inline-size;
		position: fixed;
		inset-inline-start: var(--sidebar-margin, 10px);
		inset-inline-end: 0;
		top: 0;
		bottom: 0;
		background: var(--color-grey-0);
		z-index: 10;
	}

	.workflows-container {
		display: flex;
		height: calc(100vh - 82px);
		height: calc(100dvh - 82px);
		gap: 0;
		padding: 10px 20px 10px 10px;
	}

	.workflow-sidebar-shell {
		width: 0;
		flex: 0 0 0;
		overflow: hidden;
		transition:
			width var(--duration-normal) var(--easing-default),
			flex-basis var(--duration-normal) var(--easing-default);
	}

	.workflow-sidebar-shell.drawer-open {
		width: min(325px, 28vw);
		flex-basis: min(325px, 28vw);
	}

	@media (min-width: 1100px) {
		.workflows-container.menu-open {
			gap: 20px;
		}
	}

	.workflows-start {
		flex: 1;
		min-width: 0;
		height: 100%;
		overflow: hidden;
		display: grid;
		gap: 28px;
		color: var(--color-font-primary);
		background-color: var(--color-grey-20);
		border-radius: 17px;
		box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
		position: relative;
		scroll-behavior: smooth;
	}

	.workflows-start:not(.management-view) {
		display: block;
		gap: 0;
		overflow: hidden;
	}

	#tabpanel-template {
		box-sizing: border-box;
		width: min(60rem, calc(100% - 4rem));
		margin: 0 auto;
		padding-top: 2.5rem;
		border-radius: var(--radius-16);
		background: var(--color-grey-0);
	}
	#tabpanel-template :global(.graph-panel) {
		width: 100%;
		margin-block: 0;
	}
	@media (max-width: 730px) {
		#tabpanel-template {
			width: calc(100% - 1rem);
		}
	}

	.workflow-management {
		position: absolute;
		inset: 0;
		overflow: auto;
		z-index: var(--z-index-raised-1);
		background: var(--color-grey-10);
		display: grid;
		gap: 16px;
		padding-block-end: 36px;
	}

	.workflow-management.composer-docked {
		display: flex;
		flex-direction: column;
		gap: 0;
		overflow: hidden;
		padding-block-end: 0;
	}

	.workflow-management.composer-docked .management-grid {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		padding-block-end: 2rem;
	}

	.empty-detail h2 {
		margin: 0;
	}

	.management-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 16px;
	}

	.workflow-detail {
		font-size: var(--font-size-p);
		min-width: 0;
		overflow: visible;
		border: 1px solid var(--color-grey-20);
		border-radius: var(--radius-16, 32px);
		background: var(--color-grey-10);
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.08);
	}

	button {
		border: 0;
		border-radius: var(--radius-8, 20px);
		padding: 10px 14px;
		cursor: pointer;
		font: inherit;
	}

	button:disabled {
		opacity: 0.6;
		cursor: wait;
	}

	.workflow-detail {
		padding: 0;
	}

	.unsaved-guard-backdrop {
		position: fixed;
		z-index: var(--z-index-modal, 1000);
		inset: 0;
		display: grid;
		place-items: center;
		padding: var(--spacing-6);
		background: color-mix(in srgb, var(--color-grey-100) 48%, transparent);
	}

	.unsaved-guard {
		display: grid;
		width: min(430px, 100%);
		gap: var(--spacing-5);
		padding: var(--spacing-8);
		border-radius: var(--radius-10);
		color: var(--color-font-primary);
		background: var(--color-grey-0);
		box-shadow: var(--shadow-xl);
	}

	.unsaved-guard h2,
	.unsaved-guard p {
		margin: 0;
	}
	.unsaved-guard p {
		color: var(--color-font-secondary);
	}
	.unsaved-guard div {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: var(--spacing-3);
	}
	.unsaved-guard button {
		background: var(--color-grey-20);
	}
	.unsaved-guard .primary {
		color: var(--color-font-button);
		background: var(--color-button-primary);
	}

	.blank-creator-backdrop {
		position: fixed;
		z-index: var(--z-index-modal, 1000);
		inset: 0;
		display: grid;
		place-items: center;
		padding: var(--spacing-6);
		background: color-mix(in srgb, var(--color-grey-100) 48%, transparent);
	}

	.blank-creator {
		width: min(460px, 100%);
		padding: var(--spacing-8);
		border-radius: var(--radius-10);
		color: var(--color-font-primary);
		background: var(--color-grey-0);
		box-shadow: var(--shadow-xl);
	}

	.blank-creator form {
		display: grid;
		gap: var(--spacing-5);
	}

	.blank-creator h2,
	.blank-creator p {
		margin: 0;
	}
	.blank-creator p,
	.blank-creator label span {
		color: var(--color-font-secondary);
	}
	.blank-creator label {
		display: grid;
		gap: var(--spacing-3);
	}
	.blank-creator input {
		box-sizing: border-box;
		width: 100%;
		padding: var(--spacing-4);
		border: 1px solid var(--color-grey-30);
		border-radius: var(--radius-6);
		color: var(--color-font-primary);
		background: var(--color-grey-0);
		font: inherit;
	}
	.blank-creator form > div {
		display: flex;
		justify-content: flex-end;
		gap: var(--spacing-3);
	}
	.blank-creator button {
		background: var(--color-grey-20);
	}
	.blank-creator .primary {
		color: var(--color-font-button);
		background: var(--color-button-primary);
	}

	.error-banner {
		margin-block-end: 14px;
		padding: 10px 12px;
		border-radius: var(--radius-8, 20px);
		color: var(--color-error, #b00020);
		background: color-mix(in srgb, var(--color-error, #b00020) 10%, transparent);
	}

	.workflow-test-now-row {
		display: flex;
		justify-content: center;
		padding: 0 1rem 2rem;
	}

	.workflow-test-now {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.55rem;
		min-width: 12rem;
		min-height: 3rem;
		padding: 0.6rem 1.4rem;
		border: 0;
		border-radius: 1rem;
		background: var(--color-button-primary);
		color: var(--color-font-button);
		box-shadow: var(--shadow-sm);
		font: inherit;
		font-weight: 650;
		cursor: pointer;
	}

	.workflow-test-now:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.empty-detail {
		min-height: 100%;
		display: grid;
		place-content: center;
		text-align: center;
		gap: 8px;
	}

	.settings-wrapper {
		display: flex;
		align-items: flex-start;
		min-width: fit-content;
	}

	@media (max-width: 760px) {
		.main-content {
			inset-inline-start: 0;
		}

		.workflows-container {
			height: calc(100vh - 66px);
			height: calc(100dvh - 66px);
			padding: 8px 10px;
			box-sizing: border-box;
		}

		/* Let the all-workflows scroll area use the space above the composer. */
		.workflows-start :global(.workspace-home-shell[data-surface='workflows'].all-items-mode) {
			display: flex;
			flex-direction: column;
		}

		.workflows-start :global(.workspace-home-shell[data-surface='workflows'].all-items-mode .workspace-scroll-layer) {
			flex: 1 1 auto;
			height: auto;
			min-height: 0;
		}

		.workflows-start :global(.workspace-home-shell[data-surface='workflows'].all-items-mode .workspace-composer-slot) {
			position: relative;
			left: auto;
			bottom: auto;
			transform: none;
			flex: 0 0 auto;
		}

		.workflow-sidebar-shell {
			position: fixed;
			z-index: var(--z-index-modal);
			inset: 82px auto 0 0;
			width: min(325px, calc(100vw - 32px));
			transform: translateX(-110%);
			transition: transform var(--duration-normal) var(--easing-default);
			box-shadow: 12px 0 30px rgba(0, 0, 0, 0.2);
		}

		.workflow-sidebar-shell.drawer-open {
			transform: translateX(0);
		}

		.management-grid {
			grid-template-columns: 1fr;
		}

		.workflow-detail {
			border-radius: var(--radius-10, 24px);
		}
	}
	/* Release the full pane's graphics surface when its entrance finishes. */
	.workflow-management.opening,
	.workflow-management.closing {
		will-change: transform, opacity;
		animation: workflow-pane-open 320ms cubic-bezier(0.32, 0, 0.2, 1) both;
	}
	.workflow-management.closing {
		animation-name: workflow-pane-close;
		pointer-events: none;
	}
	@keyframes workflow-pane-open {
		from {
			transform: translateY(100%);
			opacity: 0;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}
	@keyframes workflow-pane-close {
		from {
			transform: translateY(0);
			opacity: 1;
		}
		to {
			transform: translateY(100%);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.workflow-management,
		.workflow-management.closing {
			animation: none;
			will-change: auto;
		}
	}
</style>
