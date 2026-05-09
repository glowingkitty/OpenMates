/** Preview mock data for CodeRepoEmbedPreview. */

const defaultProps = {
  id: 'preview-code-repo-1',
  url: 'https://github.com/lemmingDev/ESP32-BLE-Gamepad',
  fullName: 'lemmingDev/ESP32-BLE-Gamepad',
  name: 'ESP32-BLE-Gamepad',
  ownerLogin: 'lemmingDev',
  ownerAvatarUrl: 'https://avatars.githubusercontent.com/u/15526971?v=4',
  description: 'Bluetooth LE Gamepad library for the ESP32',
  primaryLanguage: 'C++',
  licenseName: 'MIT License',
  licenseSpdxId: 'MIT',
  stars: 1516,
  forks: 250,
  openIssues: 35,
  updatedAt: '2026-05-08T09:02:54Z',
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Repo fullscreen clicked')
};

export default defaultProps;

export const variants = {
  processing: { ...defaultProps, id: 'preview-code-repo-processing', status: 'processing' as const },
  error: { ...defaultProps, id: 'preview-code-repo-error', status: 'error' as const },
  cancelled: { ...defaultProps, id: 'preview-code-repo-cancelled', status: 'cancelled' as const },
  mobile: { ...defaultProps, id: 'preview-code-repo-mobile', isMobile: true }
};
