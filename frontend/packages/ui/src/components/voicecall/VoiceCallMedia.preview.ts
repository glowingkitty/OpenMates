const noop = () => {};
export default {
  cameraStream: null, cameraEnabled: false, cameraFacing: 'environment', expanded: true,
  displayedMedia: { embedId: 'preview-image', kind: 'image', url: '/images/examples/group1.jpg' },
  onExpandedChange: noop, onShowCamera: noop, onFlipCamera: noop, onPrevious: noop, onNext: noop,
};
export const variants = {
  video: { displayedMedia: { embedId: 'preview-video', kind: 'video', url: '/store-examples/video-generate-1.mp4' } },
  camera: { displayedMedia: null, cameraEnabled: true },
  collapsed: { expanded: false },
};
