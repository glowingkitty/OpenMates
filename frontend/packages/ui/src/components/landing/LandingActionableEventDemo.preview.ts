/** Actionable landing event demo, playing once with the web-sourced event shape. */
const defaultProps = { playing: true, onComplete: () => {} };
export default defaultProps;
export const variants = {
  paused: { ...defaultProps, playing: false },
};
