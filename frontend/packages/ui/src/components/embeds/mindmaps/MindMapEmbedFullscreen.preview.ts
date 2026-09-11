/**
 * Public, deterministic mindmap fullscreen inspection fixture.
 * Exercises the original renderer without an account or provider request.
 * The default includes branching and a dependency link for design review.
 * Invalid-source recovery is available as a URL-selected variant.
 * See docs/architecture/mindmap-fullscreen-design-proposal.md.
 */
const model = {
  openmatesType: 'mindmap', schemaVersion: 1, title: 'Launch Plan', rootId: 'launch',
  nodes: [
    { id: 'launch', label: 'Launch Plan', description: 'Coordinate launch workstreams', children: ['research', 'build', 'ship'] },
    { id: 'research', label: 'Audience Research', children: ['interviews', 'survey'] },
    { id: 'interviews', label: 'Customer Interviews' },
    { id: 'survey', label: 'Survey' },
    { id: 'build', label: 'Build', children: ['copy', 'landing'] },
    { id: 'copy', label: 'Messaging' },
    { id: 'landing', label: 'Landing Page' },
    { id: 'ship', label: 'Ship', children: ['announcement', 'followup'] },
    { id: 'announcement', label: 'Announcement' },
    { id: 'followup', label: 'Follow-up' }
  ],
  edges: [{ source: 'research', target: 'copy', type: 'dependency' }],
  view: { layout: 'radial-tree', collapsedNodeIds: [] }
};

const defaultProps = {
  data: { decodedContent: { source_json: JSON.stringify(model), title: model.title }, attrs: {} },
  onClose: () => {}
};

export default defaultProps;
export const variants = {
  invalidSource: {
    ...defaultProps,
    data: { decodedContent: { source_json: 'This is not a valid mindmap document', title: 'Invalid map' }, attrs: {} }
  }
};
