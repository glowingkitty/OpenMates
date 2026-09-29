<!--
  Workflows route for the authenticated web app.
  Provides the V1 server-backed workflow list, Shortcuts-style detail/editor
  shell, example workflow creation, manual runs, and run history.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Workflows/WorkflowStore.swift
  - apple/OpenMates/Sources/Features/Workflows/WorkflowViews.swift
-->

<script lang="ts">
	import { onMount } from 'svelte';
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
	import WorkflowVoiceInput from '@repo/ui/components/workflows/WorkflowVoiceInput.svelte';
	import WorkflowPendingPreview from '@repo/ui/components/workflows/WorkflowPendingPreview.svelte';
	import { committedWorkflows, getWorkflowInstruction, submitWorkflowInstruction, undoWorkflowInstruction, workflowNodeChanges, type WorkflowInputChange, type WorkflowInputSession } from '@repo/ui/services/workflowInputService';
	import WorkflowRunHistory from '@repo/ui/components/workflows/WorkflowRunHistory.svelte';
	import WorkflowVersionHistory from '@repo/ui/components/workflows/WorkflowVersionHistory.svelte';
	import { userProfile } from '@repo/ui/stores/userProfile.ts';
	import type { WorkflowDetail, WorkflowGraph, WorkflowRun, WorkflowSummary } from '@repo/ui';

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
	let identityResetSignal = $state(0);
	let hydratedEditorWorkflowId = $state<string | null>(null);
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
	let pendingSaveSessionId = $state<string | null>(null);
	let pendingSaveMessage = $state<string | null>(null);
	let pendingPreviewWorkflow = $state<WorkflowDetail | null>(null);
	let pendingPreviewTargetId = $state<string | null>(null);
	let pendingResumeStarted = false;
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
	let showManageView = $derived(canRenderWorkflowData && isManageView);
	let visibleWorkflowGreetingName = $derived(
		canRenderWorkflowData ? workflowGreetingName : 'there'
	);
	let visibleWorkflowLandingItems = $derived(canRenderWorkflowData ? workflowLandingItems : []);
	let editorActivationReady = $derived(
		editorGraph ? workflowGraphReady(editorGraph, { requireSchedule: true }) : false
	);
	let savedRunReady = $derived(
		selectedWorkflow ? workflowGraphReady(selectedWorkflow.graph) : false
	);
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
		void initializeWorkflowsRoute();

		return () => {
			routeAlive = false;
			window.removeEventListener('hashchange', syncWorkflowHashFromLocation);
			window.removeEventListener('popstate', syncWorkflowHashFromLocation);
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
		const workflow = await workflowWorkspaceStore.selectWorkflow(workflowId);
		if (sameWorkflowAlreadySelected && editorDirty) return;
		selectedRunContentRetention = workflow.run_content_retention ?? 'last_5';
		resetEditor(workflow);
		aiChange = null;
		aiSession = null;
		undoConflict = false;
		const sessionId = localStorage.getItem(`workflow-ai-session:${workflowId}`);
		if (sessionId) {
			void getWorkflowInstruction(sessionId).then(session => {
				if (workflowHashState.workflowId !== workflowId || session.status !== 'executed') return;
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
		void workflowWorkspaceStore.loadWorkflows().catch((loadError) => {
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
				if (session.status !== 'executed' || !session.undo_available) {
					sessionStorage.removeItem('workflow-ai-last-batch');
					return;
				}
				createdAiSession = session;
				newWorkflowIds = saved.workflowIds;
				createdAiWorkflowIds = saved.workflowIds;
				authoringAssumptions = session.assumptions ?? [];
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
			const pending = JSON.parse(raw) as { sessionId: string; instruction: string; workflowId?: string };
			pendingSaveSessionId = pending.sessionId;
			pendingSaveMessage = $text('workflows.builder.ai_saving');
			void authorWorkflow(pending.instruction, pending.workflowId, pending.sessionId);
		} catch {
			sessionStorage.removeItem('workflow-ai-pending');
		}
	});

	$effect(() => {
		if (!canLoadWorkflows) return;
		const requestedWorkflow = requestedWorkflowId
			? workflows.find((workflow) => workflow.id === requestedWorkflowId)
			: null;
		const workflowId = requestedWorkflow?.id ?? null;
		if (requestedWorkflowId && !workflowId && $workflowWorkspaceStore.listStatus === 'ready') {
			openWorkflowHome(true);
			return;
		}
		if (!workflowId || workflowId === $workflowWorkspaceStore.selectedWorkflowId) return;
		void selectWorkflow(workflowId).catch((selectError) => {
			console.error('[WorkflowsRoute] Failed to select workflow:', selectError);
		});
	});

	$effect(() => {
		if (!selectedWorkflow || hydratedEditorWorkflowId === selectedWorkflow.id) return;
		selectedRunContentRetention = selectedWorkflow.run_content_retention ?? 'last_5';
		resetEditor(selectedWorkflow);
		hydratedEditorWorkflowId = selectedWorkflow.id;
	});

	$effect(() => {
		const generation = workflowWorkspaceStore.getGeneration();
		const storeSelectedWorkflowId = $workflowWorkspaceStore.selectedWorkflowId;
		if (!canRenderWorkflowData || generation !== observedWorkflowGeneration) {
			observedWorkflowGeneration = generation;
			routeError = null;
		}
		void storeSelectedWorkflowId;
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

	function submitEditorInstruction(text: string): void {
		if (!selectedWorkflow || !text.trim() || pendingSaveSessionId) return;
		editorInstruction = text.trim();
		requestNavigation(() => authorWorkflow(text.trim(), selectedWorkflow.id));
	}

	function handoffWorkflowClarification(instruction: string): void {
		// This same-origin deep link creates a new chat and sends the exact request with the focus mention.
		sessionStorage.setItem('docs_auto_send', 'true');
		sessionStorage.setItem('workflow_clarification_new_chat', 'true');
		void goto(`/#message=${encodeURIComponent(`@focus:workflows:clarify_workflows ${instruction}`)}`);
	}

	async function authorWorkflow(instruction: string, workflowId?: string, existingSessionId?: string): Promise<void> {
		if (saving) return;
		const before = workflowId && selectedWorkflow?.id === workflowId ? selectedWorkflow : null;
		authoringAssumptions = [];
		undoConflict = false;
		pendingPreviewWorkflow = null;
		pendingPreviewTargetId = workflowId ?? null;
		saving = true;
		routeError = null;
		try {
			let session = existingSessionId
				? await getWorkflowInstruction(existingSessionId)
				: await submitWorkflowInstruction(instruction, workflowId);
			let pendingChecks = 0;
			while (session.status === 'queued' || session.status === 'saving') {
				pendingSaveSessionId = session.session_id;
				pendingSaveMessage = session.message || $text('workflows.builder.ai_saving');
				pendingPreviewWorkflow = session.preview_workflow ?? pendingPreviewWorkflow;
				pendingPreviewTargetId = workflowId ?? null;
				authoringAssumptions = session.assumptions ?? authoringAssumptions;
				sessionStorage.setItem('workflow-ai-pending', JSON.stringify({ sessionId: session.session_id, instruction, workflowId }));
				await new Promise(resolve => setTimeout(resolve, pendingChecks++ < 2 ? 500 : 1500));
				if (!routeAlive) return;
				session = await getWorkflowInstruction(session.session_id);
			}
			pendingSaveSessionId = null;
			pendingSaveMessage = null;
			pendingPreviewWorkflow = null;
			pendingPreviewTargetId = null;
			sessionStorage.removeItem('workflow-ai-pending');
			if (session.status === 'needs_clarification') {
				handoffWorkflowClarification(instruction);
				return;
			}
			if (session.status === 'draft') {
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
			if (session.status !== 'executed') {
				routeError = session.error || session.message || $text('workflows.builder.ai_failed');
				return;
			}
			const committed = committedWorkflows(session);
			if (!committed.length) {
				routeError = $text('workflows.builder.ai_missing_result');
				return;
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
				openWorkflowHome();
			}
			if (workflowId) {
				const updated = committed.find(item => item.id === workflowId);
				if (updated) {
					const mutation = session.mutations?.find(item => item.target_id === workflowId);
					workflowWorkspaceStore.upsertWorkflow(updated);
					resetEditor(updated);
					identityResetSignal += 1;
					aiChange = session.changes?.find(change => change.workflow_id === workflowId) ?? {
						workflow_id: workflowId,
						...workflowNodeChanges(before?.graph.nodes ?? mutation?.before?.graph?.nodes ?? [], updated.graph.nodes)
					};
					aiSession = session;
					localStorage.setItem(`workflow-ai-session:${workflowId}`, session.session_id);
				}
			}
			workflowInputText = '';
			editorInstruction = '';
		} catch (cause) {
			routeError = cause instanceof Error ? cause.message : $text('workflows.builder.ai_failed');
		} finally {
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
			sessionStorage.removeItem('workflow-ai-last-batch');
			newWorkflowIds = newWorkflowIds.filter(id => !createdAiWorkflowIds.includes(id));
			createdAiWorkflowIds = [];
			authoringAssumptions = [];
			await workflowWorkspaceStore.loadWorkflows({ force: true });
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
			const pending = JSON.parse(raw) as { sessionId: string; instruction: string; workflowId?: string };
			void authorWorkflow(pending.instruction, pending.workflowId, pending.sessionId);
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

	function newsBriefGraph(): WorkflowGraph {
		return weeklyEventsGraph();
	}

	function resetEditor(workflow: WorkflowDetail) {
		editorTitle = workflow.title;
		editorDescription = workflow.description ?? '';
		editorGraph = cloneGraph(workflow.graph);
		editorDirty = false;
		hydratedEditorWorkflowId = workflow.id;
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
						<svelte:fragment slot="composer">
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
							/>
							{#if voiceTarget === 'home'}
								<WorkflowVoiceInput onSubmit={submitWorkflowInput} onReview={(raw) => { workflowInputText = raw; }} onClose={() => { voiceTarget = null; }}/>
							{/if}
							{#if pendingSaveSessionId}<div class="workflow-ai-pending" data-testid="workflow-ai-pending" role="status"><span>{pendingSaveMessage || $text('workflows.builder.ai_saving')}</span>{#if !saving}<button type="button" onclick={resumePendingSave}>{$text('workflows.builder.ai_check_status')}</button>{/if}</div>{/if}
							{#if pendingSaveSessionId && pendingPreviewWorkflow && pendingPreviewTargetId === null}
								<WorkflowPendingPreview workflow={pendingPreviewWorkflow} mode="landing"/>
							{/if}
							{#if authoringAssumptions.length}<p class="workflow-ai-assumptions" data-testid="workflow-ai-assumptions" role="status">{authoringAssumptions.join(' ')}</p>{/if}
							{#if createdAiSession?.undo_available}<button type="button" class="workflow-ai-created-undo" data-testid="workflow-ai-created-undo" disabled={saving} onclick={() => void undoCreatedAiChanges()}>{$text('workflows.builder.ai_undo')}</button>{/if}
						</svelte:fragment>
					</WorkspaceHomeShell>
				{/if}

				{#if showManageView}
					<section
						class="workflow-management"
						class:opening={workflowOpening}
						class:closing={workflowClosing}
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
								{#if selectedWorkflow}
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
										onOpenRuns={() => requestWorkflowTab('runs')}
										runsHref={workflowStateHref(selectedWorkflow.id, 'runs')}
									/>
									{/key}

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
														{#if authoringReminder}<p
																class="workflow-authoring-reminder"
																data-testid="workflow-authoring-reminder"
																role="status"
															>
																{authoringReminder}
															</p>{/if}
													<div class="workflow-ai-composer" data-testid="workflow-ai-editor-composer">
														<WorkspacePromptComposer surface="workflows" bind:value={editorInstruction}
															placeholder={$text('workflows.builder.ai_edit_placeholder')} submitLabel={$text('workflows.builder.ai_edit_submit')} submittingLabel={$text('workflows.builder.ai_edit_submitting')}
															disabled={saving || !!pendingSaveSessionId} submitting={saving} testId="workflow-ai-edit-composer" inputTestId="workflow-ai-edit-textarea"
															submitTestId="workflow-ai-edit-submit" micTestId="workflow-ai-edit-mic" onSubmit={submitEditorInstruction}
															onMicClick={() => { voiceTarget = 'editor'; }}/>
														{#if voiceTarget === 'editor'}<WorkflowVoiceInput onSubmit={submitEditorInstruction} onReview={(raw) => { editorInstruction = raw; }} onClose={() => { voiceTarget = null; }}/>{/if}
														{#if pendingSaveSessionId}<div class="workflow-ai-pending" data-testid="workflow-ai-pending" role="status"><span>{pendingSaveMessage || $text('workflows.builder.ai_saving')}</span>{#if !saving}<button type="button" onclick={resumePendingSave}>{$text('workflows.builder.ai_check_status')}</button>{/if}</div>{/if}
													</div>
													{#if aiChange && !pendingPreviewWorkflow && aiChange.workflow_id === selectedWorkflow.id}
														<div class="workflow-ai-changes" data-testid="workflow-ai-changes" role="status">
															<strong>{$text('workflows.builder.ai_changes_saved')}</strong>
															{#if authoringAssumptions.length}<p>{authoringAssumptions.join(' ')}</p>{/if}
															{#if aiChange.removed_nodes.length}<p>{$text('workflows.builder.ai_removed')} {aiChange.removed_nodes.map(node => node.title).join(', ')}</p>{/if}
															{#if aiChange.added_node_ids.length}<p>{aiChange.added_node_ids.length} {$text('workflows.builder.ai_added_nodes')}</p>{/if}
															{#if aiChange.edited_node_ids.length}<p>{aiChange.edited_node_ids.length} {$text('workflows.builder.ai_edited_nodes')}</p>{/if}
															<button type="button" data-testid="workflow-ai-undo" disabled={saving || !aiSession?.undo_available} onclick={() => void undoAiChanges()}>{$text('workflows.builder.ai_undo')}</button>
															{#if undoConflict}<button type="button" data-testid="workflow-ai-open-history" onclick={() => document.querySelector<HTMLButtonElement>('[data-testid="workflow-version-selector"]')?.click()}>{$text('workflows.version_history.title')}</button>{/if}
														</div>
													{/if}
													{#if pendingSaveSessionId && pendingPreviewWorkflow && pendingPreviewTargetId === selectedWorkflow.id}
														<WorkflowPendingPreview workflow={pendingPreviewWorkflow} mode="editor"/>
													{:else}
													<WorkflowGraphRenderer
														bind:this={workflowGraphRef}
														graph={editorGraph}
														aiAddedNodeIds={aiChange?.workflow_id === selectedWorkflow.id ? aiChange.added_node_ids : []}
														aiEditedNodeIds={aiChange?.workflow_id === selectedWorkflow.id ? aiChange.edited_node_ids : []}
															workflowId={selectedWorkflow.id}
															onChange={updateEditorGraph}
															onSave={saveNodeGraph}
																/>
													{/if}
													{#if hasTimeTrigger && !pendingPreviewWorkflow}
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
	.workflow-ai-composer{margin:1.5rem auto;max-width:42rem;padding:0 1rem}
	.workflow-ai-assumptions{max-width:42rem;margin:.75rem auto;text-align:center;color:var(--color-font-secondary);font-size:var(--font-size-small)}
	.workflow-ai-created-undo{display:block;margin:.75rem auto;border:0;border-radius:.7rem;padding:.55rem .9rem;background:var(--color-button-primary);color:var(--color-font-button);font:inherit;cursor:pointer}
	.workflow-ai-pending{display:flex;justify-content:center;align-items:center;gap:.75rem;max-width:42rem;margin:.75rem auto;color:var(--color-font-secondary)}
	.workflow-ai-pending button{border:1px solid var(--color-button-primary);border-radius:.7rem;padding:.35rem .7rem;background:transparent;color:var(--color-primary);font:inherit;cursor:pointer}
	.workflow-ai-changes{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:1rem 1.25rem;border:1px solid var(--color-button-primary);border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary)}
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

	.workflow-authoring-reminder {
		width: min(42rem, calc(100% - 2rem));
		box-sizing: border-box;
		margin: 1rem auto 0;
		padding: 0.75rem 1rem;
		border-radius: var(--radius-8, 20px);
		color: var(--color-font-secondary);
		background: var(--color-grey-10);
		font-size: var(--font-size-small, 0.875rem);
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
