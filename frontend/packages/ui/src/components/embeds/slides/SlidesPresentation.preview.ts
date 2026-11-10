/**
 * Preview mock data for SlidesPresentation (audience view and presenter view).
 * Access at: /dev/preview/embeds/slides/SlidesPresentation
 * Variants: aspect16x10, aspect4x3, presenter, presenterBlocked.
 * Without a session id the presenter view runs without a second window.
 */
import { sampleDeck } from './slidesPreviewFixture';

const defaultProps = {
  markup: sampleDeck('16:9'),
  startIndex: 0,
  mode: 'single' as const,
  /** Counts exits on window so the component spec can assert Esc and the exit control. */
  onExit: () => {
    const target = window as unknown as { __slidesExitCount?: number };
    target.__slidesExitCount = (target.__slidesExitCount ?? 0) + 1;
  }
};

export default defaultProps;

export const variants = {
  aspect16x10: { ...defaultProps, markup: sampleDeck('16:10') },
  aspect4x3: { ...defaultProps, markup: sampleDeck('4:3') },
  presenter: { ...defaultProps, mode: 'presenter' as const },
  presenterBlocked: {
    ...defaultProps,
    mode: 'presenter' as const,
    notice: 'Your browser blocked the second window. Presenting in this window instead.'
  },
  singleBlocked: {
    ...defaultProps,
    notice: 'Your browser blocked the second window. Presenting in this window instead.'
  }
};
