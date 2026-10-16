/** Synthetic Chat Settings states. Preview browser must block writes and provide
 * local /v1/user-tasks, /v1/user-plans, usage and shared manifest fixtures. */
export default { tab: 'plan', shared: false };
export const variants = {
  tasks: { tab: 'tasks', shared: false },
  files: { tab: 'files', shared: false },
  usage: { tab: 'usage', shared: false },
  share: { tab: 'share', shared: false },
  shared: { tab: 'share', shared: true },
  public: { tab: 'share', example: true },
  anonymous: { tab: 'share', anonymous: true },
  publicUsage: { tab: 'usage', example: true, exampleChatId: 'example-audio-speak-openmates-welcome-message' },
};
