/** A result asset, using the existing sanitized OpenMates SVG route. */
const defaultProps = {
  id: 'design-icon-result-preview', icon_id: 'tabler:home', prefix: 'tabler', name: 'home',
  display_name: 'Home', collection_name: 'Tabler Icons', license_title: 'MIT',
  svg_path: '/v1/apps/design/icons/iconify/tabler/home.svg', onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  missing: { ...defaultProps, svg_path: undefined, collection_name: undefined, license_title: undefined },
  longTitle: { ...defaultProps, display_name: 'Accessible home and neighbourhood navigation symbol from the open source collection' },
};
