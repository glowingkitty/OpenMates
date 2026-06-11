/**
 * Preview mock data for VideoCreateEmbedFullscreen.
 *
 * Shows the synced video player + interactive timeline for AI-generated videos.
 * Access at: /dev/preview/embeds/videos
 */

const PRODUCT_LAUNCH_CODE = `import { Sequence, AbsoluteFill, Audio } from "remotion";

export const ProductLaunch: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={240}>
        <GradientBg />
      </Sequence>
      <Sequence from={0} durationInFrames={60}>
        <TitleCard text="Introducing OpenMates" />
      </Sequence>
      <Sequence from={60} durationInFrames={60}>
        <FeatureList />
      </Sequence>
      <Sequence from={120} durationInFrames={60}>
        <ClientEncryptionDemo />
      </Sequence>
      <Sequence from={180} durationInFrames={60}>
        <CallToAction />
      </Sequence>
      <Audio src="/static/music/background.mp3" />
    </AbsoluteFill>
  );
};

export const Root = () => (
  <Composition
    id="product-launch"
    component={ProductLaunch}
    durationInFrames={240}
    fps={30}
    width={1920}
    height={1080}
  />
);`;

const DATA_VIZ_CODE = `import { Sequence, AbsoluteFill } from "remotion";

export const DataViz: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={270}>
        <DarkBackground />
      </Sequence>
      <Sequence from={0} durationInFrames={210}>
        <ChartTitle />
      </Sequence>
      <Sequence from={30} durationInFrames={180}>
        <BarChart />
      </Sequence>
      <Sequence from={120} durationInFrames={90}>
        <GrowthLabel />
      </Sequence>
      <Sequence from={210} durationInFrames={60}>
        <OutroCard />
      </Sequence>
    </AbsoluteFill>
  );
};

export const Root = () => (
  <Composition
    id="data-viz"
    component={DataViz}
    durationInFrames={270}
    fps={30}
    width={1920}
    height={1080}
  />
);`;

/** Default props — product launch video with synced timeline */
const defaultProps = {
	data: {
		decodedContent: {
			filename: 'ProductLaunch.tsx',
			status: 'finished' as const,
			remotion_source: PRODUCT_LAUNCH_CODE,
			current_source_version: 1,
			active_render_version: 1,
			render_metadata: { runtime_seconds: 12, charged_credits: 0 }
		},
		embedData: { status: 'finished' },
		attrs: { app_id: 'videos' }
	},
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants */
export const variants = {
	/** Data visualization video */
	dataViz: {
		data: {
			decodedContent: {
				filename: 'DataViz.tsx',
				status: 'finished' as const,
				remotion_source: DATA_VIZ_CODE,
				current_source_version: 1,
				active_render_version: 1
			},
			embedData: { status: 'finished' },
			attrs: { app_id: 'videos' }
		},
		onClose: () => {}
	},

	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	}
};
