<!--
  Video Timeline Parser Preview — Dev Testing Page.
  Shows multiple hardcoded Remotion code examples with:
  1. The raw Remotion TSX source code
  2. An auto-generated timeline visualization parsed from the code
  3. (Future) The rendered video output from E2B

  URL: /dev/preview/video-timeline
  Purpose: Validate the AST-based timeline parser before building the full
  Video Create skill. Tests whether Remotion code can be reliably converted
  to a visual timeline without LLM-generated manifests.
-->
<script lang="ts">
	import { parseRemotionTimeline, type VideoManifest } from '@repo/ui/utils/remotionTimelineParser';

	// ─── Example Remotion compositions ──────────────────────────────

	const examples: { title: string; description: string; code: string }[] = [
		{
			title: 'Simple Series (Sequential Scenes)',
			description: 'Three colored scenes playing back-to-back using <Series>. The most basic Remotion pattern.',
			code: `import { Series, AbsoluteFill } from "remotion";

const Square: React.FC<{ color: string }> = ({ color }) => (
  <AbsoluteFill style={{ backgroundColor: color }} />
);

export const SimpleScenes: React.FC = () => {
  return (
    <Series>
      <Series.Sequence durationInFrames={90}>
        <Square color="#3498db" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={60}>
        <Square color="#2ecc71" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={120}>
        <Square color="#e74c3c" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={30}>
        <Square color="#f39c12" />
      </Series.Sequence>
    </Series>
  );
};

export const Root = () => (
  <Composition
    id="simple-scenes"
    component={SimpleScenes}
    durationInFrames={300}
    fps={30}
    width={1920}
    height={1080}
  />
);`,
		},
		{
			title: 'Product Launch Promo',
			description: 'Multi-layer composition with overlapping sequences — title, features, and CTA on separate tracks with background music.',
			code: `import { Sequence, AbsoluteFill, Audio, spring, useCurrentFrame, useVideoConfig } from "remotion";

const GradientBg: React.FC = () => (
  <AbsoluteFill style={{
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
  }} />
);

const TitleCard: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame();
  const opacity = spring({ frame, fps: 30, from: 0, to: 1 });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <h1 style={{ color: "white", fontSize: 80, opacity }}>{text}</h1>
    </AbsoluteFill>
  );
};

const FeatureList: React.FC = () => (
  <AbsoluteFill style={{ justifyContent: "center", padding: 100 }}>
    <ul style={{ color: "white", fontSize: 40 }}>
      <li>Lightning fast performance</li>
      <li>Client-side encryption</li>
      <li>Beautiful design</li>
    </ul>
  </AbsoluteFill>
);

const CallToAction: React.FC = () => (
  <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
    <div style={{ background: "white", borderRadius: 20, padding: "30px 60px" }}>
      <h2 style={{ color: "#764ba2", fontSize: 60 }}>Try it free</h2>
    </div>
  </AbsoluteFill>
);

export const ProductLaunch: React.FC = () => {
  return (
    <AbsoluteFill>
      {/* Background layer - full duration */}
      <Sequence from={0} durationInFrames={450}>
        <GradientBg />
      </Sequence>

      {/* Title - first 5 seconds */}
      <Sequence from={0} durationInFrames={150}>
        <TitleCard text="Introducing OpenMates" />
      </Sequence>

      {/* Features - seconds 5-10 */}
      <Sequence from={150} durationInFrames={150}>
        <FeatureList />
      </Sequence>

      {/* CTA - seconds 10-15 */}
      <Sequence from={300} durationInFrames={150}>
        <CallToAction />
      </Sequence>

      {/* Background music */}
      <Audio src="/static/music/background.mp3" />
    </AbsoluteFill>
  );
};

export const Root = () => (
  <Composition
    id="product-launch"
    component={ProductLaunch}
    durationInFrames={450}
    fps={30}
    width={1920}
    height={1080}
  />
);`,
		},
		{
			title: 'Text Animation Slideshow',
			description: 'Series of text cards with spring animations, each appearing sequentially. Common pattern for social media videos.',
			code: `import { Series, AbsoluteFill, spring, useCurrentFrame, useVideoConfig, Sequence } from "remotion";

const AnimatedText: React.FC<{ text: string; color: string }> = ({ text, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ frame, fps, config: { damping: 12 } });
  const opacity = Math.min(1, frame / 10);

  return (
    <AbsoluteFill style={{
      justifyContent: "center",
      alignItems: "center",
      backgroundColor: color,
    }}>
      <h1 style={{
        color: "white",
        fontSize: 72,
        transform: \`scale(\${scale})\`,
        opacity,
        fontFamily: "Lexend Deca",
      }}>
        {text}
      </h1>
    </AbsoluteFill>
  );
};

const Logo: React.FC = () => (
  <AbsoluteFill style={{
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#1a1a2e",
  }}>
    <img src="/static/logo.png" style={{ width: 200 }} />
  </AbsoluteFill>
);

export const TextSlideshow: React.FC = () => {
  return (
    <Series>
      <Series.Sequence durationInFrames={90}>
        <AnimatedText text="Privacy First" color="#2d3436" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90}>
        <AnimatedText text="Open Source" color="#0984e3" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90}>
        <AnimatedText text="Your Data, Your Rules" color="#6c5ce7" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90}>
        <AnimatedText text="No Tracking" color="#00b894" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90}>
        <AnimatedText text="Encrypted on Your Device" color="#e17055" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={60}>
        <Logo />
      </Series.Sequence>
    </Series>
  );
};

export const Root = () => (
  <Composition
    id="text-slideshow"
    component={TextSlideshow}
    durationInFrames={510}
    fps={30}
    width={1080}
    height={1080}
  />
);`,
		},
		{
			title: 'Data Visualization',
			description: 'Animated chart with intro, data reveal, and outro. Uses overlapping layers for background + foreground content.',
			code: `import { Sequence, AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

const DarkBackground: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#0f0f23" }} />
);

const ChartTitle: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 20], [0, 1]);
  return (
    <div style={{
      position: "absolute",
      top: 60,
      left: 80,
      color: "white",
      fontSize: 48,
      fontWeight: 600,
      opacity,
    }}>
      Monthly Active Users
    </div>
  );
};

const BarChart: React.FC = () => {
  const frame = useCurrentFrame();
  const bars = [
    { label: "Jan", value: 45, color: "#3B82F6" },
    { label: "Feb", value: 62, color: "#8B5CF6" },
    { label: "Mar", value: 78, color: "#EC4899" },
    { label: "Apr", value: 95, color: "#F59E0B" },
    { label: "May", value: 120, color: "#10B981" },
  ];
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", padding: "0 80px 120px" }}>
      <div style={{ display: "flex", gap: 40, alignItems: "flex-end" }}>
        {bars.map((bar, i) => {
          const height = interpolate(
            frame,
            [i * 15, i * 15 + 30],
            [0, bar.value * 4],
            { extrapolateRight: "clamp" }
          );
          return (
            <div key={bar.label} style={{ textAlign: "center" }}>
              <div style={{
                width: 80,
                height,
                backgroundColor: bar.color,
                borderRadius: "8px 8px 0 0",
              }} />
              <span style={{ color: "#999", fontSize: 24 }}>{bar.label}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const GrowthLabel: React.FC = () => (
  <div style={{
    position: "absolute",
    bottom: 40,
    right: 80,
    color: "#10B981",
    fontSize: 36,
  }}>
    +167% growth
  </div>
);

const OutroCard: React.FC = () => (
  <AbsoluteFill style={{
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#0f0f23",
  }}>
    <h1 style={{ color: "white", fontSize: 64 }}>openmates.org</h1>
  </AbsoluteFill>
);

export const DataViz: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={300}>
        <DarkBackground />
      </Sequence>

      <Sequence from={0} durationInFrames={240}>
        <ChartTitle />
      </Sequence>

      <Sequence from={30} durationInFrames={210}>
        <BarChart />
      </Sequence>

      <Sequence from={120} durationInFrames={120}>
        <GrowthLabel />
      </Sequence>

      <Sequence from={240} durationInFrames={60}>
        <OutroCard />
      </Sequence>
    </AbsoluteFill>
  );
};

export const Root = () => (
  <Composition
    id="data-viz"
    component={DataViz}
    durationInFrames={300}
    fps={30}
    width={1920}
    height={1080}
  />
);`,
		},
		{
			title: 'Video with Captions',
			description: 'A video clip with timed subtitle overlays. Demonstrates mixing media with text sequences.',
			code: `import { Sequence, AbsoluteFill, OffthreadVideo, Audio } from "remotion";

const Subtitle: React.FC<{ text: string }> = ({ text }) => (
  <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 80 }}>
    <div style={{
      background: "rgba(0,0,0,0.7)",
      color: "white",
      padding: "12px 32px",
      borderRadius: 8,
      fontSize: 36,
      fontFamily: "Lexend Deca",
    }}>
      {text}
    </div>
  </AbsoluteFill>
);

export const CaptionedVideo: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={600}>
        <OffthreadVideo src="/static/clips/demo-recording.mp4" />
      </Sequence>

      <Sequence from={30} durationInFrames={90}>
        <Subtitle text="Welcome to OpenMates" />
      </Sequence>

      <Sequence from={150} durationInFrames={90}>
        <Subtitle text="Your privacy-first AI assistant" />
      </Sequence>

      <Sequence from={270} durationInFrames={90}>
        <Subtitle text="Encrypted on your device" />
      </Sequence>

      <Sequence from={390} durationInFrames={90}>
        <Subtitle text="Open source and transparent" />
      </Sequence>

      <Sequence from={510} durationInFrames={90}>
        <Subtitle text="Try it at openmates.org" />
      </Sequence>

      <Audio src="/static/music/ambient.mp3" />
    </AbsoluteFill>
  );
};

export const Root = () => (
  <Composition
    id="captioned-video"
    component={CaptionedVideo}
    durationInFrames={600}
    fps={30}
    width={1920}
    height={1080}
  />
);`,
		},
	];

	// ─── Parse all examples ─────────────────────────────────────────

	interface ParsedExample {
		title: string;
		description: string;
		code: string;
		manifest: VideoManifest;
	}

	const parsed: ParsedExample[] = examples.map((ex) => ({
		...ex,
		manifest: parseRemotionTimeline(ex.code),
	}));

	// ─── UI State ───────────────────────────────────────────────────

	let expandedCode: Set<number> = $state(new Set());

	function toggleCode(index: number) {
		const next = new Set(expandedCode);
		if (next.has(index)) next.delete(index);
		else next.add(index);
		expandedCode = next;
	}

	function rulerMarks(totalSec: number): number[] {
		const step = totalSec <= 5 ? 1 : totalSec <= 20 ? 2 : 5;
		return Array.from({ length: Math.floor(totalSec / step) + 1 }, (_, i) => i * step);
	}

	function formatTime(frames: number, fps: number): string {
		const seconds = frames / fps;
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;
	}
</script>

<div class="page">
	<header class="page-header">
		<h1>Video Timeline Parser Preview</h1>
		<p class="subtitle">
			Remotion TSX code parsed into visual timelines via static analysis.
			No LLM manifest needed — the timeline is extracted directly from the code.
		</p>
	</header>

	{#each parsed as example, idx}
		<section class="example-card">
			<div class="example-header">
				<h2>{example.title}</h2>
				<p class="example-desc">{example.description}</p>
				<div class="meta-pills">
					<span class="pill">{example.manifest.meta.durationSeconds}s</span>
					<span class="pill">{example.manifest.meta.fps}fps</span>
					<span class="pill">{example.manifest.meta.width}x{example.manifest.meta.height}</span>
					<span class="pill">{example.manifest.tracks.length} tracks</span>
				</div>
			</div>

			<!-- Timeline Visualization -->
			<div class="timeline-container">
				<!-- Time ruler -->
				<div class="time-ruler">
					<div class="track-label-spacer"></div>
					<div class="ruler-bar">
						{#each rulerMarks(example.manifest.meta.durationSeconds) as sec}
							<span
								class="ruler-mark"
								style="left: {(sec / example.manifest.meta.durationSeconds) * 100}%"
							>
								{sec}s
							</span>
						{/each}
					</div>
				</div>

				<!-- Tracks -->
				{#each example.manifest.tracks as track}
					<div class="track-row">
						<div class="track-label">
							<span class="track-type-icon">
								{#if track.type === 'audio'}
									&#9835;
								{:else if track.type === 'effect'}
									&#10022;
								{:else}
									&#9632;
								{/if}
							</span>
							{track.name}
						</div>
						<div class="track-items">
							{#each track.items as item}
								{@const totalFrames = example.manifest.meta.durationInFrames}
								{@const leftPct = (item.from / totalFrames) * 100}
								{@const widthPct = (item.durationInFrames / totalFrames) * 100}
								<div
									class="track-item"
									style="left: {leftPct}%; width: {widthPct}%; background-color: {item.color};"
									title="{item.label} ({formatTime(item.from, example.manifest.meta.fps)} - {formatTime(item.from + item.durationInFrames, example.manifest.meta.fps)})"
								>
									<span class="item-label">{item.label}</span>
									<span class="item-duration">
										{formatTime(item.durationInFrames, example.manifest.meta.fps)}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>

			<!-- Video placeholder -->
			<div class="video-placeholder">
				<div class="video-placeholder-inner">
					<span class="play-icon">&#9654;</span>
					<span>Video render via E2B (not yet connected)</span>
				</div>
			</div>

			<!-- Code toggle -->
			<button class="code-toggle" onclick={() => toggleCode(idx)}>
				{expandedCode.has(idx) ? 'Hide' : 'Show'} Remotion Code
				<span class="toggle-arrow">{expandedCode.has(idx) ? '▲' : '▼'}</span>
			</button>

			{#if expandedCode.has(idx)}
				<div class="code-block">
					<pre><code>{example.code}</code></pre>
				</div>
			{/if}

			<!-- Parsed manifest (debug) -->
			<details class="manifest-debug">
				<summary>Parsed manifest JSON</summary>
				<pre><code>{JSON.stringify(example.manifest, null, 2)}</code></pre>
			</details>
		</section>
	{/each}
</div>

<style>
	.page {
		max-width: 1100px;
		margin: 0 auto;
		padding: 40px 24px 80px;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		color: var(--color-font-primary, #1a1a2e);
	}

	.page-header {
		margin-bottom: 40px;
	}

	.page-header h1 {
		font-size: 28px;
		font-weight: 600;
		margin: 0 0 8px;
	}

	.subtitle {
		font-size: 14px;
		color: var(--color-font-tertiary, #666);
		margin: 0;
		line-height: 1.6;
		max-width: 700px;
	}

	/* ─── Example Card ─── */

	.example-card {
		margin-bottom: 48px;
		border: 1px solid var(--color-grey-25, #e0e0e0);
		border-radius: 12px;
		overflow: hidden;
		background: var(--color-grey-0, #fff);
	}

	.example-header {
		padding: 24px 24px 16px;
	}

	.example-header h2 {
		font-size: 20px;
		font-weight: 600;
		margin: 0 0 6px;
	}

	.example-desc {
		font-size: 13px;
		color: var(--color-font-tertiary, #666);
		margin: 0 0 12px;
		line-height: 1.5;
	}

	.meta-pills {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}

	.pill {
		padding: 3px 10px;
		border-radius: 12px;
		font-size: 11px;
		font-weight: 500;
		background: var(--color-grey-15, #f0f0f0);
		color: var(--color-font-secondary, #444);
	}

	/* ─── Timeline ─── */

	.timeline-container {
		padding: 16px 24px 20px;
		background: var(--color-grey-5, #fafafa);
		border-top: 1px solid var(--color-grey-20, #e8e8e8);
		border-bottom: 1px solid var(--color-grey-20, #e8e8e8);
	}

	.time-ruler {
		display: flex;
		align-items: flex-end;
		margin-bottom: 8px;
		height: 20px;
	}

	.track-label-spacer {
		width: 100px;
		min-width: 100px;
	}

	.ruler-bar {
		flex: 1;
		position: relative;
		height: 20px;
		border-bottom: 1px solid var(--color-grey-30, #ccc);
	}

	.ruler-mark {
		position: absolute;
		bottom: 2px;
		transform: translateX(-50%);
		font-size: 10px;
		color: var(--color-font-tertiary, #888);
		font-variant-numeric: tabular-nums;
	}

	.track-row {
		display: flex;
		align-items: stretch;
		margin-bottom: 6px;
		min-height: 36px;
	}

	.track-label {
		width: 100px;
		min-width: 100px;
		font-size: 12px;
		font-weight: 500;
		color: var(--color-font-secondary, #555);
		display: flex;
		align-items: center;
		gap: 6px;
		padding-right: 12px;
	}

	.track-type-icon {
		font-size: 10px;
		opacity: 0.6;
	}

	.track-items {
		flex: 1;
		position: relative;
		height: 36px;
		background: var(--color-grey-10, #f4f4f4);
		border-radius: 6px;
		overflow: hidden;
	}

	.track-item {
		position: absolute;
		top: 2px;
		height: 32px;
		border-radius: 5px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 8px;
		box-sizing: border-box;
		cursor: default;
		transition: filter 0.15s;
		overflow: hidden;
		min-width: 2px;
	}

	.track-item:hover {
		filter: brightness(1.15);
	}

	.item-label {
		font-size: 11px;
		font-weight: 500;
		color: white;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
	}

	.item-duration {
		font-size: 10px;
		color: rgba(255, 255, 255, 0.8);
		white-space: nowrap;
		margin-left: 6px;
		flex-shrink: 0;
	}

	/* ─── Video Placeholder ─── */

	.video-placeholder {
		padding: 16px 24px;
	}

	.video-placeholder-inner {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 32px;
		border: 2px dashed var(--color-grey-25, #ddd);
		border-radius: 10px;
		color: var(--color-font-tertiary, #999);
		font-size: 14px;
	}

	.play-icon {
		font-size: 24px;
		opacity: 0.4;
	}

	/* ─── Code Block ─── */

	.code-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		width: 100%;
		padding: 10px;
		border: none;
		border-top: 1px solid var(--color-grey-20, #e8e8e8);
		background: var(--color-grey-5, #fafafa);
		color: var(--color-font-secondary, #555);
		font-size: 13px;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		cursor: pointer;
		transition: background 0.15s;
	}

	.code-toggle:hover {
		background: var(--color-grey-15, #eee);
	}

	.toggle-arrow {
		font-size: 10px;
	}

	.code-block {
		border-top: 1px solid var(--color-grey-20, #e8e8e8);
		max-height: 400px;
		overflow-y: auto;
	}

	.code-block pre {
		margin: 0;
		padding: 16px 24px;
		font-size: 12px;
		line-height: 1.6;
		font-family: 'Courier New', monospace;
		background: var(--color-grey-5, #fafafa);
		white-space: pre-wrap;
		word-break: break-word;
	}

	.code-block code {
		color: var(--color-font-primary, #1a1a2e);
	}

	/* ─── Manifest Debug ─── */

	.manifest-debug {
		border-top: 1px solid var(--color-grey-20, #e8e8e8);
		font-size: 12px;
	}

	.manifest-debug summary {
		padding: 8px 24px;
		cursor: pointer;
		color: var(--color-font-tertiary, #888);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		background: var(--color-grey-5, #fafafa);
	}

	.manifest-debug summary:hover {
		color: var(--color-font-secondary, #555);
	}

	.manifest-debug pre {
		margin: 0;
		padding: 12px 24px;
		font-size: 11px;
		line-height: 1.5;
		font-family: 'Courier New', monospace;
		background: var(--color-grey-10, #f0f0f0);
		max-height: 300px;
		overflow-y: auto;
	}
</style>
