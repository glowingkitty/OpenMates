/** Saved icon result preserving provider, recoloring, copy and export behavior. */
const result = {
  icon_id: 'tabler:home', prefix: 'tabler', name: 'home', display_name: 'Home', collection_name: 'Tabler Icons',
  license_title: 'MIT', author_name: 'Paweł Kuna', provider: 'Iconify', width: 24, height: 24,
  palette: false, svg_path: '/v1/apps/design/icons/iconify/tabler/home.svg',
};
const defaultProps = { data: { decodedContent: result }, embedId: 'design-icon-result-preview', onClose: () => {} };
export default defaultProps;
export const variants = {
  missing: { data: { decodedContent: { display_name: 'Unavailable icon' } } },
  palette: { data: { decodedContent: { ...result, palette: true } } },
};
