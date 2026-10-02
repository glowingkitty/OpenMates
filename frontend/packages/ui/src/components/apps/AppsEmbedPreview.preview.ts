import { rootId, childIds, ready } from './AppsInlineResults.preview';
export { ready };
const onFullscreen = () => window.dispatchEvent(new Event('apps-embed-preview-open'));
export default { embedId: rootId, appId: 'web', skillId: 'search', onFullscreen };
export const variants = { child: { embedId: childIds[0], appId: 'web', skillId: 'search', onFullscreen } };
