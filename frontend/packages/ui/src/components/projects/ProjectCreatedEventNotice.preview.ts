/** Preview fixtures for the chat-history "Created <name> project" system event. */
export default { projectName: 'Recipe Manager', onOpen: () => {}, onUndo: () => {} };
export const variants = {
  undoing: { projectName: 'Recipe Manager', undoing: true, onOpen: () => {}, onUndo: () => {} },
  undone: { projectName: 'Recipe Manager', undone: true, onOpen: () => {} },
  failed: { projectName: 'Recipe Manager', failed: true, onOpen: () => {}, onUndo: () => {} },
  noUndo: { projectName: 'Recipe Manager', onOpen: () => {}, onUndo: undefined },
};
