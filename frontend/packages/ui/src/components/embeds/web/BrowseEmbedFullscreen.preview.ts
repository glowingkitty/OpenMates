import props from './BrowseEmbedPreview.preview';
const defaults = { data: { decodedContent: props.content }, onClose: () => {} };
export default defaults;
export const variants = {
  processing: { ...defaults, data: { decodedContent: { status: 'processing', task: 'Find the documentation' } } },
  mobile: defaults,
};
