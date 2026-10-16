const digest = (character: string) => character.repeat(64);
export default {
  memories: [
    { id: 'app:diagrams:type-flowchart', title: 'Diagram Design: Flowchart', source: 'app', app_id: 'diagrams', revision: digest('a'), body: '- Use clear direction.\n- Keep labels short.' },
    { id: 'project:example:guide', title: 'Project design guide', source: 'project', project_id: 'Fictional Project', revision: digest('b'), body: '- Keep primary actions visible.' },
  ],
};
