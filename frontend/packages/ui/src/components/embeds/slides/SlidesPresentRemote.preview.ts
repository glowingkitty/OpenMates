/**
 * Preview mock data for SlidesPresentRemote (phone remote control).
 * Access at: /dev/preview/embeds/slides/SlidesPresentRemote
 * Variants: second, notPresenting. Moves are recorded on window.__slidesRemoteCalls.
 */
import { sampleDeck } from './slidesPreviewFixture';

function record(entry: string) {
  const target = window as unknown as { __slidesRemoteCalls?: string[] };
  (target.__slidesRemoteCalls ??= []).push(entry);
}

const defaultProps = {
  markup: sampleDeck('16:9'),
  position: { index: 0, step: 0 },
  presenting: true,
  onAction: (action: string) => record(action),
  onGoto: (index: number) => record(`goto:${index}`),
  onClose: () => record('close')
};

export default defaultProps;

export const variants = {
  second: { ...defaultProps, position: { index: 1, step: 0 } },
  notPresenting: { ...defaultProps, presenting: false }
};
