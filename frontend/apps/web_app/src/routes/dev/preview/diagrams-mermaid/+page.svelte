<!--
  frontend/apps/web_app/src/routes/dev/preview/diagrams-mermaid/+page.svelte

  Deterministic dev preview for Diagrams/Mermaid embeds. This page avoids the
  generic embed showcase route so Mermaid renderer E2E coverage stays small and
  does not depend on the large route's parser-sensitive Svelte boundary setup.
-->

<script lang="ts">
	import MermaidDiagramEmbedPreview from '@repo/ui/components/embeds/diagrams/MermaidDiagramEmbedPreview.svelte';
	import MermaidDiagramEmbedFullscreen from '@repo/ui/components/embeds/diagrams/MermaidDiagramEmbedFullscreen.svelte';

	const diagramCode = `sequenceDiagram
    participant User
    participant Web as Web App
    participant API
    participant Mail as Email Service
    User->>Web: Enters email
    Web->>API: POST /auth/start-email
    API->>Mail: Send verification code
    Mail-->>User: Code arrives
    User->>Web: Enters code
    Web->>API: POST /auth/verify-email
    API-->>Web: Session token
    Web-->>User: Account ready`;

	const decodedContent = {
		type: 'mermaid',
		app_id: 'diagrams',
		skill_id: 'mermaid',
		title: 'Email Signup Sequence',
		diagram_kind: 'sequenceDiagram',
		diagram_code: diagramCode,
		line_count: diagramCode.split('\n').length,
		embed_ref: 'email-signup-sequence-a1B',
		status: 'finished',
		version_number: 2
	};

	const fullscreenData = {
		decodedContent,
		embedData: {
			status: 'finished',
			type: 'mermaid',
			app_id: 'diagrams',
			skill_id: 'mermaid'
		},
		attrs: {
			app_id: 'diagrams',
			skill_id: 'mermaid',
			type: 'mermaid'
		}
	};
</script>

<svelte:head>
	<title>Mermaid Diagram Embed Preview</title>
</svelte:head>

<main class="page" data-testid="diagrams-mermaid-preview-page">
	<section class="section" data-testid="skill-section">
		<h1>Diagrams Mermaid Embed</h1>
		<p>Deterministic preview and fullscreen fixture for Mermaid renderer contracts.</p>

		<h2>Preview</h2>
		<div class="preview-shell">
			<MermaidDiagramEmbedPreview
				id="preview-diagrams-mermaid-1"
				title="Email Signup Sequence"
				diagram_kind="sequenceDiagram"
				{diagramCode}
				diagram_code={diagramCode}
				line_count={diagramCode.split('\n').length}
				status="finished"
				onFullscreen={() => {}}
			/>
		</div>

		<h2>Fullscreen</h2>
		<div class="fullscreen-shell" data-testid="fs-clip">
			<MermaidDiagramEmbedFullscreen
				embedId="preview-diagrams-mermaid-fullscreen-1"
				data={fullscreenData}
				onClose={() => {}}
			/>
		</div>
	</section>
</main>

<style>
	.page {
		min-height: 100vh;
		padding: 32px;
		background: var(--color-grey-5);
		color: var(--color-font-primary);
	}

	.section {
		max-width: 1100px;
		margin: 0 auto;
		display: grid;
		gap: 24px;
	}

	.preview-shell {
		max-width: 360px;
	}

	.fullscreen-shell {
		height: 780px;
		border-radius: var(--radius-4);
		overflow: hidden;
		background: var(--color-grey-0);
	}
</style>
