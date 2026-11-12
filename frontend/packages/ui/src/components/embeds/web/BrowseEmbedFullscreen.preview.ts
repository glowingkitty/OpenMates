import props from './BrowseEmbedPreview.preview';
const defaults = { data: { decodedContent: props.content }, onClose: () => {} };
export default defaults;
export const variants = {
  processing: { ...defaults, data: { decodedContent: { status: 'processing', task: 'Find the documentation' } } },
  partial: { ...defaults, data: { decodedContent: { status: 'finished', results: [{ status: 'completed', title: 'Example Domain', url: 'https://example.com/',
    data_json: '{"items":[{"name":"Sample"}]}', missing: ['items[0].price', 'items[1].rating', 'purpose'] }] } } },
  mobile: defaults,
};
