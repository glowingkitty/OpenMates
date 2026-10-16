import darkHtml from './diagramHtmlExampleDark.html?raw';
import lightHtml from './diagramHtmlExampleLight.html?raw';
import { diagramHtmlDecorativeFixture } from './diagramHtmlDecorativeFixture';
import { generatedDiagramArtifacts } from './diagramHtmlGeneratedArtifacts';

const decodedContent = {
  type: 'diagram_html', app_id: 'diagrams', skill_id: 'html', title: 'High-level architecture · End-to-end stack',
  diagram_kind: 'architecture', html_source: darkHtml, render_width: 1240, render_height: 900,
  schema_version: 1, version_number: 1, status: 'finished'
};
const defaultProps = {
  embedId: 'preview-diagrams-html-fullscreen-dark',
  onClose: () => {},
  fixtureEditable: true,
  data: { decodedContent, embedData: { status: 'finished', type: 'diagram_html', app_id: 'diagrams', skill_id: 'html' },
    attrs: { type: 'diagram_html', app_id: 'diagrams', skill_id: 'html' } }
};
export default defaultProps;
export const variants = {
  light: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-light', data: { ...defaultProps.data, decodedContent: { ...decodedContent, html_source: lightHtml } } },
  decorativeSvg: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-decorative', data: { ...defaultProps.data, decodedContent: { ...decodedContent, html_source: diagramHtmlDecorativeFixture } } },
  generatedPasswordless: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-generated-passwordless',
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, ...generatedDiagramArtifacts.generatedPasswordless } } },
  generatedSupport: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-generated-support',
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, ...generatedDiagramArtifacts.generatedSupport } } },
  generatedSupportClean: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-generated-support-clean',
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, ...generatedDiagramArtifacts.generatedSupportClean } } },
  generatedPasswordlessClean: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-generated-passwordless-clean',
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, ...generatedDiagramArtifacts.generatedPasswordlessClean } } },
  generatedShopClean: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-generated-shop-clean',
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, ...generatedDiagramArtifacts.generatedShopClean } } },
  editable: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-editable' },
  chatLifecycle: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-chat-lifecycle',
    chatId: 'preview-diagrams-html-chat',
    onClose: () => document.querySelector('[data-testid="embed-fullscreen-overlay"]')?.remove() },
  unsafe: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-unsafe', fixtureEditable: false,
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, html_source: '<html><body><svg viewBox="0 0 100 100"></svg><img src="https://evil.example/x"></body></html>' } } },
  processing: { ...defaultProps, embedId: 'preview-diagrams-html-fullscreen-processing', fixtureEditable: false,
    data: { ...defaultProps.data, decodedContent: { ...decodedContent, html_source: '', status: 'processing' } } }
};
