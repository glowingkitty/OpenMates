<!--
  BrandHeader — Logo + headline + feature list block for marketing graphics.

  Configurable via props: headline, subtitle, features list.
  Used across OG images, social media templates, etc.

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	let {
		headline = 'Digital team mates',
		subtitle = 'For everyone.',
		features = [
			'AI for everyday tasks & learning',
			'Privacy focus',
			'No subscription',
			'Fair pay per use'
		],
		logoSize = 40,
		headlineSize = '2.75rem',
		featureSize = '1.125rem',
		showLogo = true,
		showFeatures = true
	}: {
		headline?: string;
		subtitle?: string;
		features?: string[];
		logoSize?: number;
		headlineSize?: string;
		featureSize?: string;
		showLogo?: boolean;
		showFeatures?: boolean;
	} = $props();
</script>

<div class="brand-header">
	{#if showLogo}
		<div class="brand-logo">
			<img
				src="/favicon.svg"
				alt="OpenMates logo"
				class="brand-logo-icon"
				style="width: {logoSize}px; height: {logoSize}px;"
			/>
			<span class="brand-logo-name"><span class="brand-logo-open">Open</span>Mates</span>
		</div>
	{/if}

	<h1 class="brand-slogan" style="font-size: {headlineSize};">
		{headline}<br />
		<mark>{subtitle}</mark>
	</h1>

	{#if showFeatures && features.length > 0}
		<ul class="brand-features">
			{#each features as feature}
				<li style="font-size: {featureSize};">
					<span class="brand-check">&#x2714;</span>
					{feature}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.brand-header {
		display: flex;
		flex-direction: column;
		justify-content: center;
		position: relative;
		z-index: 1;
	}

	.brand-logo {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 24px;
	}

	.brand-logo-icon {
		flex-shrink: 0;
	}

	.brand-logo-name {
		font-size: 1.375rem;
		font-weight: 700;
		color: #f0f0f0;
		letter-spacing: -0.01em;
	}

	.brand-logo-open {
		color: #7a9bf0;
	}

	.brand-slogan {
		font-weight: 800;
		line-height: 1.15;
		letter-spacing: -0.03em;
		color: #f0f0f0;
		margin: 0 0 28px;
	}

	.brand-slogan mark {
		background: linear-gradient(135deg, #4867cd 9.04%, #5a85eb 90.06%);
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
		background-color: transparent;
	}

	.brand-features {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.brand-features li {
		font-weight: 500;
		color: #e0e0e0;
		display: flex;
		align-items: center;
		gap: 12px;
		line-height: 1.3;
	}

	.brand-check {
		color: #28c840;
		font-size: 1.25rem;
		flex-shrink: 0;
		line-height: 1;
	}
</style>
