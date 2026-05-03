/**
 * Preview mock data for VideoCreateEmbedPreview.
 *
 * Provides sample Remotion video manifests and states for the component preview system.
 * Access at: /dev/preview/embeds/videos
 */

import { parseRemotionTimeline } from '../../../utils/remotionTimelineParser';

const PRODUCT_LAUNCH_CODE = `import { Sequence, AbsoluteFill, Audio } from "remotion";

export const ProductLaunch: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={450}>
        <GradientBg />
      </Sequence>
      <Sequence from={0} durationInFrames={150}>
        <TitleCard text="Introducing OpenMates" />
      </Sequence>
      <Sequence from={150} durationInFrames={150}>
        <FeatureList />
      </Sequence>
      <Sequence from={300} durationInFrames={150}>
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
    durationInFrames={450}
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

const productLaunchManifest = parseRemotionTimeline(PRODUCT_LAUNCH_CODE);
const dataVizManifest = parseRemotionTimeline(DATA_VIZ_CODE);

/** Default props — finished video with thumbnail */
const defaultProps = {
	id: 'preview-video-create-1',
	manifest: productLaunchManifest,
	status: 'finished' as const,
	videoUrl: '/dev-fixtures/video-creation/product-launch.mp4',
	thumbnailUrl: '',
	isMobile: false,
	onFullscreen: () => {}
};

export default defaultProps;

/** Named variants */
export const variants = {
	/** Processing state — video is still rendering, show timeline */
	processing: {
		id: 'preview-video-create-processing',
		manifest: productLaunchManifest,
		status: 'processing' as const,
		isMobile: false,
		onFullscreen: () => {}
	},

	/** Data visualization — second example */
	dataViz: {
		id: 'preview-video-create-dataviz',
		manifest: dataVizManifest,
		status: 'finished' as const,
		videoUrl: '/dev-fixtures/video-creation/data-viz.mp4',
		isMobile: false,
		onFullscreen: () => {}
	},

	/** Data viz — processing state */
	dataVizProcessing: {
		id: 'preview-video-create-dataviz-proc',
		manifest: dataVizManifest,
		status: 'processing' as const,
		isMobile: false,
		onFullscreen: () => {}
	},

	/** Error state — render failed */
	error: {
		id: 'preview-video-create-error',
		manifest: productLaunchManifest,
		status: 'error' as const,
		errorMessage: 'Remotion render failed: composition "product-launch" not found',
		isMobile: false,
		onFullscreen: () => {}
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-video-create-mobile',
		isMobile: true
	}
};
