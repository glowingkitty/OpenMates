const model = {
 title: 'Low-poly research observatory', provider: 'Example Catalogue', creator_name: 'Example Artist',
 license: 'CC BY 4.0', files_count: 3, source_page_url: 'https://example.com/models/observatory',
 preview_image_url: 'https://images.example.com/models/observatory.png',
};
const defaultProps = { embedId: 'preview-model-catalog', data: { decodedContent: model }, onClose: () => {} };
export default defaultProps;
export const variants = {
 missingData: { ...defaultProps, data: { decodedContent: { title: 'Catalogue result', source_page_url: model.source_page_url } } },
 brokenImage: { ...defaultProps, data: { decodedContent: { ...model, preview_image_url: 'data:image/png;base64,invalid' } } },
};
