<script lang="ts">
	import { onMount } from 'svelte';
	import type { DemoChat as DemoChatType } from '../demo_chats/types';
	import ReadOnlyMessage from './ReadOnlyMessage.svelte';
	import { fade, fly } from 'svelte/transition';
	import { authStore } from '../stores/authStore';

	interface Props {
		demoChat: DemoChatType;
		onSignupClick?: () => void;
	}

	let { demoChat, onSignupClick }: Props = $props();

	// State for message input
	let draftMessage = $state('');
	let messageInputRef: HTMLTextAreaElement | null = $state(null);

	// Auto-resize textarea
	function handleInput(event: Event) {
		const target = event.target as HTMLTextAreaElement;
		target.style.height = 'auto';
		target.style.height = target.scrollHeight + 'px';
	}

	function handleSignupClick() {
		// Store draft message in localStorage
		if (draftMessage.trim()) {
			localStorage.setItem(`demo_draft_${demoChat.chat_id}`, draftMessage);
		}

		// Call parent handler or default to opening signup
		if (onSignupClick) {
			onSignupClick();
		} else {
			// Trigger signup flow
			window.location.hash = '#signup';
		}
	}

	onMount(() => {
		// Check for saved draft
		const savedDraft = localStorage.getItem(`demo_draft_${demoChat.chat_id}`);
		if (savedDraft) {
			draftMessage = savedDraft;
		}
	});
</script>

<div class="demo-chat-container">
	<!-- Chat Header -->
	<div class="demo-header">
		<div class="demo-badge">
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
				<path d="M8 2L9.5 5.5L13 6L10.5 9L11 12.5L8 11L5 12.5L5.5 9L3 6L6.5 5.5L8 2Z" fill="currentColor"/>
			</svg>
			<span>Demo Chat</span>
		</div>
		<h1 class="demo-title">{demoChat.title}</h1>
	</div>

	<!-- Chat Messages -->
	<div class="messages-container">
		{#each demoChat.messages as message, index (message.id)}
			<div
				class="message-wrapper"
				in:fly={{ y: 20, duration: 300, delay: index * 100 }}
			>
				<ReadOnlyMessage
					role={message.role}
					content={message.content}
				/>
			</div>
		{/each}
	</div>

	<!-- Message Input (Disabled for Demo) -->
	<div class="input-container">
		<div class="input-wrapper">
			<textarea
				bind:this={messageInputRef}
				bind:value={draftMessage}
				oninput={handleInput}
				placeholder="Type your message..."
				rows="1"
				class="message-input"
			/>
			<button
				class="signup-button"
				onclick={handleSignupClick}
				type="button"
			>
				{#if draftMessage.trim()}
					<span>Sign up to send</span>
				{:else}
					<span>Sign up to chat</span>
				{/if}
				<svg width="20" height="20" viewBox="0 0 20 20" fill="none">
					<path d="M10 4L16 10M16 10L10 16M16 10H4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
				</svg>
			</button>
		</div>
		<p class="demo-hint">
			This is a demo chat. Sign up to send messages and get AI responses!
		</p>
	</div>
</div>

<style>
	.demo-chat-container {
		display: flex;
		flex-direction: column;
		height: 100%;
		width: 100%;
		background-color: var(--color-grey-0);
	}

	.demo-header {
		padding: 20px;
		border-bottom: 1px solid var(--color-grey-20);
		background: linear-gradient(135deg, var(--color-grey-5) 0%, var(--color-grey-10) 100%);
	}

	.demo-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 12px;
		background-color: var(--color-primary);
		color: white;
		border-radius: 12px;
		font-size: 12px;
		font-weight: 600;
		margin-bottom: 12px;
	}

	.demo-badge svg {
		opacity: 0.9;
	}

	.demo-title {
		font-size: 24px;
		font-weight: 600;
		color: var(--color-grey-100);
		margin: 0;
	}

	.messages-container {
		flex: 1;
		overflow-y: auto;
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.message-wrapper {
		animation: fadeIn 0.3s ease-out;
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
			transform: translateY(10px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.input-container {
		padding: 20px;
		border-top: 1px solid var(--color-grey-20);
		background-color: var(--color-grey-5);
	}

	.input-wrapper {
		display: flex;
		gap: 12px;
		align-items: flex-end;
		background-color: white;
		border: 2px solid var(--color-grey-30);
		border-radius: 12px;
		padding: 12px;
		transition: border-color 0.2s;
	}

	.input-wrapper:focus-within {
		border-color: var(--color-primary);
	}

	.message-input {
		flex: 1;
		border: none;
		outline: none;
		resize: none;
		font-family: inherit;
		font-size: 16px;
		line-height: 1.5;
		max-height: 200px;
		overflow-y: auto;
		background: transparent;
	}

	.signup-button {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
		background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark, #0056b3) 100%);
		color: white;
		border: none;
		border-radius: 8px;
		font-weight: 600;
		font-size: 14px;
		cursor: pointer;
		transition: all 0.2s;
		white-space: nowrap;
	}

	.signup-button:hover {
		transform: translateY(-1px);
		box-shadow: 0 4px 12px rgba(0, 123, 255, 0.3);
	}

	.signup-button:active {
		transform: translateY(0);
	}

	.signup-button svg {
		width: 20px;
		height: 20px;
	}

	.demo-hint {
		margin-top: 12px;
		font-size: 13px;
		color: var(--color-grey-60);
		text-align: center;
	}

	/* Scrollbar styling */
	.messages-container::-webkit-scrollbar {
		width: 8px;
	}

	.messages-container::-webkit-scrollbar-track {
		background: transparent;
	}

	.messages-container::-webkit-scrollbar-thumb {
		background-color: var(--color-grey-40);
		border-radius: 4px;
	}

	.messages-container::-webkit-scrollbar-thumb:hover {
		background-color: var(--color-grey-50);
	}

	/* Mobile responsiveness */
	@media (max-width: 730px) {
		.demo-header {
			padding: 16px;
		}

		.demo-title {
			font-size: 20px;
		}

		.messages-container {
			padding: 16px;
		}

		.input-container {
			padding: 16px;
		}

		.signup-button span {
			display: none;
		}

		.signup-button {
			padding: 10px;
		}
	}
</style>
