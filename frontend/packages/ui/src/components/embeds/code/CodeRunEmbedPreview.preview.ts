/** Preview mock data for CodeRunEmbedPreview (cloud command in a Project sandbox). */

const defaultProps = {
  id: 'preview-code-run-1',
  command: '$ cd web-app && npm run build',
  argv: ['npm', 'run', 'build'],
  cwd: 'web-app',
  exitCode: 0,
  durationSeconds: 4.2,
  outputTail: 'dist/assets/index-Dzi6.css  2.81 kB\ndist/assets/index-Cj9r.js  3.53 kB\n✓ built in 143ms',
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  running: { ...defaultProps, id: 'preview-code-run-running', exitCode: undefined, durationSeconds: undefined,
    outputTail: undefined, status: 'processing' as const },
  failed: {
    ...defaultProps,
    id: 'preview-code-run-failed',
    command: '$ cd web-app && npx playwright test',
    argv: ['npx', 'playwright', 'test'],
    exitCode: 1,
    durationSeconds: 12.6,
    outputTail: '1 failed\n  recipes.spec.ts:8 adds a recipe',
    status: 'error' as const,
  },
  mobile: { ...defaultProps, id: 'preview-code-run-mobile', isMobile: true },
};
