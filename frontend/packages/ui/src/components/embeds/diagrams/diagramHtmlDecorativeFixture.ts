import darkHtml from './diagramHtmlExampleDark.html?raw';

/** A zero-size decorative SVG before the canonical diagram tests editor targeting. */
export const diagramHtmlDecorativeFixture = darkHtml.replace(
  '<body>',
  '<body>\n  <svg data-om-decorative="true" viewBox="0 0 10 10" aria-hidden="true" style="position:absolute;left:0;top:0;width:0;height:0;min-width:0;overflow:hidden"><path d="M 0,0 H 10 V 10 Z"/></svg>'
);
