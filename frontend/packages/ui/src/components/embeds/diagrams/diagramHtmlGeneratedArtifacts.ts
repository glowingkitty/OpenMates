import provenance from './diagramHtmlGeneratedProvenance.json';
import passwordlessHtml from './diagramHtmlGeneratedPasswordlessSequenceDark.html?raw';
import supportHtml from './diagramHtmlGeneratedSupportFlowLight.html?raw';
import supportCleanHtml from './diagramHtmlGeneratedSupportFlowLightClean.html?raw';
import passwordlessCleanHtml from './diagramHtmlGeneratedPasswordlessSequenceDarkClean.html?raw';
import shopCleanHtml from './diagramHtmlGeneratedShopArchitectureDarkClean.html?raw';

function artifact(id: string, htmlSource: string) {
  const record = provenance.find((item) => item.id === id);
  if (!record) throw new Error(`Missing generated diagram provenance: ${id}`);
  return {
    title: record.title,
    diagram_kind: record.diagram_kind,
    html_source: htmlSource,
    render_width: record.render_width,
    render_height: record.render_height,
    schema_version: 1,
    version_number: 1,
    status: 'finished' as const,
  };
}

/** Exact raw model exports; preview wrappers must never rewrite their source. */
export const generatedDiagramArtifacts = {
  generatedPasswordless: artifact('generatedPasswordless', passwordlessHtml),
  generatedSupport: artifact('generatedSupport', supportHtml),
  generatedSupportClean: artifact('generatedSupportClean', supportCleanHtml),
  generatedPasswordlessClean: artifact('generatedPasswordlessClean', passwordlessCleanHtml),
  generatedShopClean: artifact('generatedShopClean', shopCleanHtml),
};
