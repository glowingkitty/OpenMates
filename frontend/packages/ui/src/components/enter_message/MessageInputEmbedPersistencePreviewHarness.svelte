<script lang="ts">
	import { onMount, tick } from 'svelte';
	import MessageInput from './MessageInput.svelte';
	import { getEditorInstance } from '../../services/drafts/draftCore';
	import { chatDB } from '../../services/db';
	import { embedStore } from '../../services/embedStore';

	const chatId = 'synthetic-code-persistence';
	const previewRef = 'preview:code-code:synthetic-code-persistence';
	const code = 'const answer = 42;';
	const draft = {
		type: 'doc',
		content: [
			{
				type: 'paragraph',
				content: [
					{
						type: 'embed',
						attrs: {
							id: 'synthetic-code-persistence',
							type: 'code-code',
							status: 'finished',
							contentRef: previewRef,
							code,
							language: 'typescript',
							lineCount: 1
						}
					}
				]
			},
			{
				type: 'paragraph',
				content: [{ type: 'text', text: 'Draft tail' }]
			}
		]
	};
	let composer = $state<{
		setDraftContent: (id: string, content: typeof draft, version: number) => Promise<void>;
	}>();
	let ready = $state(false);
	let persistence = $state('waiting');
	let contentRef = $state('');
	let draftCode = $state('');
	let readinessChecks = $state(0);
	let sendRequests = $state(0);
	let sentContent = $state('');
	let resolvePut: (() => void) | undefined;
	let rejectPut: ((error: Error) => void) | undefined;

	onMount(() => {
		const originalPut = embedStore.put;
		const originalEnsureReady = chatDB.ensureReadyForSend;
		embedStore.put = async (ref, data, type) => {
			if (!ref.startsWith('embed:') || type !== 'code-code') {
				return originalPut.call(embedStore, ref, data, type);
			}
			persistence = 'pending';
			await new Promise<void>((resolve, reject) => {
				resolvePut = resolve;
				rejectPut = reject;
			});
		};
		chatDB.ensureReadyForSend = async () => {
			readinessChecks += 1;
		};

		let editor = getEditorInstance();
		const updateDraft = () => {
			if (!editor) return;
			editor.state.doc.descendants((node) => {
				if (node.type.name !== 'embed') return true;
				contentRef = String(node.attrs.contentRef ?? '');
				draftCode = String(node.attrs.code ?? '');
				return false;
			});
		};
		void tick().then(async () => {
			await composer?.setDraftContent(chatId, draft, 1);
			editor = getEditorInstance();
			editor?.on('update', updateDraft);
			updateDraft();
			ready = true;
		});
		return () => {
			editor?.off('update', updateDraft);
			embedStore.put = originalPut;
			chatDB.ensureReadyForSend = originalEnsureReady;
		};
	});

	function send() {
		const editor = getEditorInstance();
		if (!editor) throw new Error('Composer editor is not mounted');
		editor.view.dom.dispatchEvent(new CustomEvent('custom-send-message', { bubbles: true }));
	}

	function release() {
		persistence = 'resolved';
		resolvePut?.();
	}

	function reject() {
		persistence = 'rejected';
		rejectPut?.(new Error('Synthetic embed persistence failure'));
	}

	function recordSend(event: CustomEvent<{ message?: { content?: string } }>) {
		sendRequests += 1;
		sentContent = event.detail?.message?.content ?? '';
	}
</script>

<div
	class="fixture"
	data-testid="code-persistence-fixture"
	data-ready={ready}
	data-persistence={persistence}
	data-ref={contentRef}
	data-code={draftCode}
	data-readiness-checks={readinessChecks}
	data-send-requests={sendRequests}
	data-sent-content={sentContent}
>
	<MessageInput
		bind:this={composer}
		currentChatId={chatId}
		showActionButtons={true}
		onAssistantSpeechPreferenceChange={() => {}}
		on:sendMessage={recordSend}
	/>
	<button type="button" data-testid="fixture-send" onclick={send}>Send draft</button>
	<button type="button" data-testid="fixture-resolve" onclick={release}>Release persistence</button>
	<button type="button" data-testid="fixture-reject" onclick={reject}>Reject persistence</button>
</div>

<style>
	.fixture {
		width: min(100%, 680px);
		padding: 1rem;
		box-sizing: border-box;
	}
</style>
