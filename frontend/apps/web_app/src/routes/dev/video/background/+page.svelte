<!--
  Dev-only fullscreen animated gradient background.

  Renders the same "living gradient orbs" animation used in ChatHeader.svelte
  but stretched to fill the entire viewport, with the default OpenMates primary
  color gradient. Intended to be screen-recorded and used as a wallpaper /
  background plate for video productions.

  Route: /dev/video/background  (dev environments only — gated by /dev layout)

  Notes:
  - All scrollbars and page chrome are hidden so the recording surface is clean.
  - Orb sizes and drift distances are scaled up vs the chat header so the motion
    reads correctly at full HD / 4K resolutions.
  - Keyframes are defined locally (not reusing the shared animations.css ones)
    so this page is fully self-contained and tunable for video work.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	// Hide global scrollbars + body chrome while this page is mounted so the
	// recorded surface is pure gradient with no UI bleed-through.
	let prevHtmlOverflow = '';
	let prevBodyOverflow = '';
	let prevBodyMargin = '';

	onMount(() => {
		prevHtmlOverflow = document.documentElement.style.overflow;
		prevBodyOverflow = document.body.style.overflow;
		prevBodyMargin = document.body.style.margin;
		document.documentElement.style.overflow = 'hidden';
		document.body.style.overflow = 'hidden';
		document.body.style.margin = '0';
	});

	onDestroy(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.style.overflow = prevHtmlOverflow;
		document.body.style.overflow = prevBodyOverflow;
		document.body.style.margin = prevBodyMargin;
	});
</script>

<div class="video-bg" aria-hidden="true">
	<div class="orb orb-1"></div>
	<div class="orb orb-2"></div>
	<div class="orb orb-3"></div>
</div>

<style>
	/* Default OpenMates primary gradient (matches --color-primary in theme.generated.css):
	     start: #4867cd   end: #5a85eb
	   Orb colors mirror the chat header loading state:
	     --orb-color-a (background tint): #4867cd
	     --orb-color-b (orb glow center) : #a0beff
	*/
	.video-bg {
		position: fixed;
		inset: 0;
		width: 100vw;
		height: 100vh;
		overflow: hidden;
		background: linear-gradient(135deg, #4867cd 9.04%, #5a85eb 90.06%);
		--orb-color-a: #4867cd;
		--orb-color-b: #a0beff;
	}

	.orb {
		position: absolute;
		/* Radial gradient: solid orb-color-b core fading to transparent at the edges.
		   Matches ChatHeader's orb formula (0% / 40% / 85%) so the look is identical. */
		background: radial-gradient(
			ellipse at center,
			var(--orb-color-b) 0%,
			var(--orb-color-b) 40%,
			transparent 85%
		);
		/* Blur scaled up vs chat header (28px) since we're working at full screen.
		   90px keeps edges silky on 1080p+ recordings without killing color saturation. */
		filter: blur(90px);
		will-change: transform, border-radius;
	}

	/* Orb 1 — left/top region. Large enough to cover ~half the viewport. */
	.orb-1 {
		top: -15vh;
		left: -15vw;
		width: 75vw;
		height: 90vh;
		opacity: 0.6;
		animation:
			videoBgMorph1 11s ease-in-out infinite,
			videoBgDrift1 19s ease-in-out infinite;
	}

	/* Orb 2 — right/bottom region. */
	.orb-2 {
		bottom: -20vh;
		right: -15vw;
		width: 80vw;
		height: 95vh;
		opacity: 0.6;
		animation:
			videoBgMorph2 13s ease-in-out infinite,
			videoBgDrift2 23s ease-in-out infinite;
	}

	/* Orb 3 — center roamer, slightly smaller and more transparent so it
	   blends the two main orbs rather than dominating. */
	.orb-3 {
		top: 5vh;
		left: 25vw;
		width: 55vw;
		height: 65vh;
		opacity: 0.42;
		animation:
			videoBgMorph3 17s ease-in-out infinite,
			videoBgDrift3 29s ease-in-out infinite;
	}

	/* ── Morph keyframes ──────────────────────────────────────────────────
	   Continuously morph border-radius between organic blob shapes. Same
	   structure as ChatHeader's orbMorph1/2/3 — replicated here so this page
	   stays self-contained (no dependency on animations.css). */

	@keyframes videoBgMorph1 {
		0%   { border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%; }
		25%  { border-radius: 30% 60% 70% 40% / 50% 60% 30% 60%; }
		50%  { border-radius: 50% 50% 33% 67% / 55% 27% 73% 45%; }
		75%  { border-radius: 33% 67% 45% 55% / 30% 70% 35% 65%; }
		100% { border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%; }
	}

	@keyframes videoBgMorph2 {
		0%   { border-radius: 40% 60% 60% 40% / 40% 40% 60% 60%; }
		33%  { border-radius: 65% 35% 40% 60% / 60% 45% 55% 40%; }
		66%  { border-radius: 35% 65% 55% 45% / 45% 55% 40% 60%; }
		100% { border-radius: 40% 60% 60% 40% / 40% 40% 60% 60%; }
	}

	@keyframes videoBgMorph3 {
		0%   { border-radius: 55% 45% 38% 62% / 48% 58% 42% 52%; }
		20%  { border-radius: 42% 58% 62% 38% / 55% 38% 62% 45%; }
		40%  { border-radius: 68% 32% 45% 55% / 40% 65% 35% 60%; }
		60%  { border-radius: 38% 62% 55% 45% / 62% 42% 58% 38%; }
		80%  { border-radius: 52% 48% 32% 68% / 35% 55% 45% 65%; }
		100% { border-radius: 55% 45% 38% 62% / 48% 58% 42% 52%; }
	}

	/* ── Drift keyframes ──────────────────────────────────────────────────
	   Translate distances are scaled up (~3×) vs chat header so the motion
	   is clearly visible at fullscreen. Prime-number durations (19/23/29s)
	   prevent the three orbs from ever syncing within a normal recording. */

	@keyframes videoBgDrift1 {
		0%   { transform: translate(0px, 0px); }
		25%  { transform: translate(360px, 180px); }
		50%  { transform: translate(440px, 30px); }
		75%  { transform: translate(180px, 280px); }
		100% { transform: translate(0px, 0px); }
	}

	@keyframes videoBgDrift2 {
		0%   { transform: translate(0px, 0px); }
		30%  { transform: translate(-400px, -160px); }
		60%  { transform: translate(-220px, -380px); }
		85%  { transform: translate(-460px, -90px); }
		100% { transform: translate(0px, 0px); }
	}

	@keyframes videoBgDrift3 {
		0%   { transform: translate(0px, 0px); }
		20%  { transform: translate(-260px, 150px); }
		45%  { transform: translate(240px, 240px); }
		70%  { transform: translate(-120px, -200px); }
		100% { transform: translate(0px, 0px); }
	}

	/* Reduced-motion: keep orbs as static glows (still produces a usable frame). */
	@media (prefers-reduced-motion: reduce) {
		.orb { animation: none !important; }
	}
</style>
