/** Included memories after a memory request: an app memory, a personal one and one not on this device. */
export default {
  memories: [
    { id: 'personal:career', title: 'Career profile', appId: null },
    { id: 'personal:stack', title: 'Preferred technologies', appId: 'code' },
    { id: 'personal:missing', title: null, appId: null },
  ],
  onOpen: () => {},
};
