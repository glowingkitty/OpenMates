/** Trusted editor script inserted after validating generated markup. It has no network access. */
import editorRuntimeSource from './diagramHtmlEditorRuntime.js?raw';
import { diagramBoundsInTarget } from './diagramHtmlGeometry';

export function diagramEditorScript(token: string): string {
  // Keep the iframe program as raw source. Serializing a TypeScript function
  // after Vite transforms it captures module-scoped helpers such as __name,
  // which are unavailable inside an opaque srcdoc frame.
  const invocation = 'editorRuntime(__OM_DIAGRAM_TOKEN__, __OM_DIAGRAM_BOUNDS__);';
  const offset = editorRuntimeSource.lastIndexOf(invocation);
  if (offset < 0 || editorRuntimeSource.indexOf(invocation) !== offset) throw new Error('Invalid trusted diagram editor asset');
  return editorRuntimeSource.slice(0, offset)
    + `editorRuntime(${JSON.stringify(token)}, ${diagramBoundsInTarget.toString()});`
    + editorRuntimeSource.slice(offset + invocation.length);
}
