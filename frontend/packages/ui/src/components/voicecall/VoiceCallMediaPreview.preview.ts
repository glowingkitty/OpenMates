export default {};
export const variants = {
  camera: { initialKind: 'camera' },
  generatedWithCamera: { initialCamera: true, multiple: true },
  video: { initialKind: 'video' },
  collapsed: { initialExpanded: false },
  error: { initialKind:'camera', initialError:'Camera access was denied.' },
};
