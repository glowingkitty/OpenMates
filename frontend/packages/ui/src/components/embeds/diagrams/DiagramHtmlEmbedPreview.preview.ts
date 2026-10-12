import darkHtml from './diagramHtmlExampleDark.html?raw';
import lightHtml from './diagramHtmlExampleLight.html?raw';
import { diagramHtmlDecorativeFixture } from './diagramHtmlDecorativeFixture';
import { generatedDiagramArtifacts } from './diagramHtmlGeneratedArtifacts';

export const diagramHtmlFixtureDark = darkHtml;
export const diagramHtmlFixtureLight = lightHtml;

const defaultProps = {
  id: 'preview-diagrams-html-dark',
  title: 'High-level architecture · End-to-end stack',
  diagram_kind: 'architecture',
  html_source: darkHtml,
  render_width: 1240,
  render_height: 900,
  schema_version: 1,
  version_number: 1,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {}
};
export default defaultProps;
export const variants = {
  light: { ...defaultProps, id: 'preview-diagrams-html-light', html_source: lightHtml },
  decorativeSvg: { ...defaultProps, id: 'preview-diagrams-html-decorative', html_source: diagramHtmlDecorativeFixture },
  generatedPasswordless: { ...defaultProps, id: 'preview-diagrams-html-generated-passwordless', ...generatedDiagramArtifacts.generatedPasswordless },
  generatedSupport: { ...defaultProps, id: 'preview-diagrams-html-generated-support', ...generatedDiagramArtifacts.generatedSupport },
  generatedSupportClean: { ...defaultProps, id: 'preview-diagrams-html-generated-support-clean', ...generatedDiagramArtifacts.generatedSupportClean },
  generatedPasswordlessClean: { ...defaultProps, id: 'preview-diagrams-html-generated-passwordless-clean', ...generatedDiagramArtifacts.generatedPasswordlessClean },
  generatedShopClean: { ...defaultProps, id: 'preview-diagrams-html-generated-shop-clean', ...generatedDiagramArtifacts.generatedShopClean },
  mobile: { ...defaultProps, id: 'preview-diagrams-html-mobile', isMobile: true },
  processing: { ...defaultProps, id: 'preview-diagrams-html-processing', status: 'processing' as const, html_source: '' },
  error: { ...defaultProps, id: 'preview-diagrams-html-error', status: 'error' as const, html_source: '' },
  unsafe: { ...defaultProps, id: 'preview-diagrams-html-unsafe', html_source: '<html><body><script>alert(1)</script><svg viewBox="0 0 100 100"></svg></body></html>' }
};
