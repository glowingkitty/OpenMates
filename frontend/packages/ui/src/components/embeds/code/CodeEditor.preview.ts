/**
 * Preview of CodeEditor, the editor of a code file embed fullscreen.
 * Access at: /dev/preview/embeds/code/CodeEditor?chrome=0
 * Save only calls the onSave prop here; the real save runs through the client core.
 */
const sampleCode = `export function add(a: number, b: number): number {
  return a + b;
}
`;

const defaultProps = {
  code: sampleCode,
  onSave: async (code: string) => {
    console.info('[CodeEditor preview] saved', code.length);
  },
  onCancel: () => {}
};

export default defaultProps;

export const variants = {
  /** The save was rejected because the file changed elsewhere. */
  conflict: {
    ...defaultProps,
    error: 'This was changed elsewhere, so your edit was not saved. Reload and try again.',
    onReload: () => {}
  },
  /** A new blank file. */
  blank: { ...defaultProps, code: '' }
};
