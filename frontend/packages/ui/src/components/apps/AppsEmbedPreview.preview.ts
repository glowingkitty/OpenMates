import { rootId, childIds, ready } from './AppsInlineResults.preview';
export { ready };
const onFullscreen = () => window.dispatchEvent(new Event('apps-embed-preview-open'));
export default { embedId: rootId, appId: 'web', skillId: 'search', onFullscreen };
const mapsPlace = { embedId: 'preview-maps-place-label', appId: 'maps', skillId: 'search', embedType: 'maps-place', onFullscreen,
  content: { type: 'place_result', name: 'Evening Coffee', formatted_address: 'Example Street 1, Berlin', types: ['cafe', 'food', 'point_of_interest', 'establishment'], rating: 4.7 } };
export const variants = {
  child: { embedId: childIds[0], appId: 'web', skillId: 'search', onFullscreen },
  mapsPlace,
  mapsPlaceUnknown: { ...mapsPlace, content: { ...mapsPlace.content, types: ['point_of_interest', 'establishment'] } },
};
