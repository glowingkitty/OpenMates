import type {
  ProjectFolderViewModel,
  ProjectItemViewModel,
  ProjectSourceViewModel,
  ProjectViewModel,
} from '../../services/projectService';
import '@fontsource-variable/lexend-deca';
import taskBoardPreview from '../tasks/TaskBoard.preview';
import { item as chatItem, presentation as chatPresentation } from './ProjectChatPreview.preview';

const now = Math.floor(Date.now() / 1000);
const project: ProjectViewModel = {
  project_id: 'preview-project',
  name: 'OpenMates',
  description: 'Digital team mates for everyday tasks, projects & learning. Privacy & user interests first.',
  icon: 'folder',
  projectKey: new Uint8Array(32),
  encrypted: {
    project_id: 'preview-project', encrypted_project_key: 'preview', encrypted_name: 'preview',
    encrypted_description: 'preview', encrypted_icon: 'preview', created_at: now,
    updated_at: now, last_opened_at: now, item_count: 4,
  },
};
const folders: ProjectFolderViewModel[] = [
  { folder_id: 'backend', name: 'Backend', parentHash: null, encrypted: { folder_id: 'backend', hashed_project_id: 'preview-project-hash', encrypted_name: 'preview', created_at: now, updated_at: now, position: 0 } },
  { folder_id: 'research', name: 'Research', parentHash: null, encrypted: { folder_id: 'research', hashed_project_id: 'preview-project-hash', encrypted_name: 'preview', created_at: now - 20, updated_at: now - 20, position: 1 } },
];
const connectedSource = {
  source_id: 'source-preview', source_type: 'local_git_repository', displayName: 'OpenMates repository',
  metadata: { root: '/workspace/OpenMates' }, capabilities: ['read'], status: 'connected', sourceSessionId: null, keyEpoch: null,
  encrypted: {
    source_id: 'source-preview', source_type: 'local_git_repository', encrypted_display_name: 'preview', encrypted_metadata: 'preview',
    capabilities: ['read'], status: 'connected', created_at: now, updated_at: now,
  },
} satisfies ProjectSourceViewModel;
const items: ProjectItemViewModel[] = [
  {
    project_item_id: 'project-source', item_type: 'embed', target_id: 'preview-code', displayName: 'ProjectsPage.svelte', metadata: { embed_type: 'code-code' },
    encrypted: { project_item_id: 'project-source', item_type: 'embed', target_id_hash: 'preview-code-hash', target_id_encrypted: 'preview', created_at: now - 10, updated_at: now - 10, position: 0 },
  },
  {
    project_item_id: 'project-brief', item_type: 'embed', target_id: 'preview-document', displayName: 'Project brief', metadata: { embed_type: 'docs-doc' },
    encrypted: { project_item_id: 'project-brief', item_type: 'embed', target_id_hash: 'preview-doc-hash', target_id_encrypted: 'preview', created_at: now - 30, updated_at: now - 30, position: 1 },
  },
  {
    project_item_id: 'project-file', item_type: 'embed', target_id: 'preview-file', displayName: 'architecture.pdf', metadata: { embed_type: 'pdf' },
    encrypted: { project_item_id: 'project-file', item_type: 'embed', target_id_hash: 'preview-file-hash', target_id_encrypted: 'preview', created_at: now - 40, updated_at: now - 40, position: 2 },
  },
];
const largeStoredItems: ProjectItemViewModel[] = Array.from({ length: 105 }, (_, index) => {
  const name = index === 0 ? 'needle-stored-root.md' : `stored-file-${String(index).padStart(3, '0')}.md`;
  return {
    project_item_id: `large-stored-${index}`,
    item_type: 'embed',
    target_id: `large-stored-target-${index}`,
    displayName: name,
    metadata: { embed_type: 'code-code' },
    encrypted: {
      project_item_id: `large-stored-${index}`, item_type: 'embed',
      target_id_hash: `large-stored-hash-${index}`, target_id_encrypted: 'preview',
      created_at: now - 100 - index, updated_at: now - 100 - index, position: index + 3,
    },
  };
});
const nestedStoredItem: ProjectItemViewModel = {
  project_item_id: 'large-stored-nested', item_type: 'embed', target_id: 'large-stored-nested-target',
  displayName: 'needle-stored-nested.md',
  metadata: { embed_type: 'code-code', source: 'hosted_project_file', path: 'guides/needle-stored-nested.md' },
  encrypted: {
    project_item_id: 'large-stored-nested', item_type: 'embed', target_id_hash: 'large-stored-nested-hash',
    target_id_encrypted: 'preview', created_at: now - 210, updated_at: now - 210, position: 109,
  },
};
const largeRemoteEntries = [
  ...Array.from({ length: 125 }, (_, index) => ({
    path: index === 0 ? 'needle-current.ts' : `remote-file-${String(index).padStart(3, '0')}.ts`,
    kind: 'file' as const, sizeBytes: 1024 + index,
  })),
  { path: 'nested', kind: 'directory' as const, children: [{ path: 'nested/needle-child.ts', kind: 'file' as const }] },
  { path: 'nested/needle-child.ts', kind: 'file' as const, sizeBytes: 2048 },
];
const legacyRemoteEntries = Array.from({ length: 500 }, (_, index) => ({
  path: `legacy-file-${String(index).padStart(3, '0')}.ts`, kind: 'file' as const, sizeBytes: 1024 + index,
}));
const embeds = {
  'preview-code': {
    embedData: { embed_id: 'preview-code', type: 'code-code', status: 'finished' },
    decodedContent: {
      type: 'code-code', language: 'svelte', filename: 'ProjectsPage.svelte', line_count: 84,
      code: `<script lang="ts">\n  let activeTab = $state('overview');\n  const tabs = ['Overview', 'Folders', 'Tasks'];\n</script>\n\n<section class="project-workspace">\n  <!-- Shared project context -->\n</section>`,
    },
  },
  'preview-document': {
    embedData: { embed_id: 'preview-document', type: 'docs-doc', status: 'finished' },
    decodedContent: {
      type: 'docs-doc', title: 'Project brief', word_count: 428,
      html: '<h1>Project brief</h1><p>A calm workspace for planning, research, and shipping useful work.</p><h2>Goals</h2><ul><li>Keep context together</li><li>Make next steps clear</li></ul>',
    },
  },
  'preview-file': {
    embedData: { embed_id: 'preview-file', type: 'pdf', status: 'finished' },
    decodedContent: {
      type: 'pdf', app_id: 'pdf', skill_id: 'upload', filename: 'architecture.pdf',
      file_type: 'application/pdf', file_size: 184_320, page_count: 12,
    },
  },
};
const folderCardContents = {
  backend: [
    { name: 'api', kind: 'folder' as const, detail: '12 items' },
    { name: 'websockets.py', kind: 'file' as const, detail: '18 KB' },
    { name: 'main_processor.py', kind: 'file' as const, detail: '31 KB' },
  ],
  research: [
    { name: 'Product requirements', kind: 'file' as const, detail: 'DOCX' },
    { name: 'Design references', kind: 'folder' as const, detail: '6 items' },
  ],
};
const projectTasks = taskBoardPreview.tasks.map((task) => ({
  ...task,
  linkedProjectIds: task.linkedProjectIds.length > 0 ? [project.project_id] : [],
}));
function emitAction(action: string, target?: unknown): void {
  window.dispatchEvent(new CustomEvent('project-workspace-preview-action', { detail: { action, target } }));
}
const overviewProps = {
  variant: 'main' as const,
  onNewChat: (target: unknown) => emitAction('chat', target),
  onNewPlan: (target: unknown) => emitAction('plan', target),
  onNewWorkflow: (target: unknown) => emitAction('workflow', target),
  previewState: { project, folders, items, sources: [], embeds, folderCardContents, readme: { status: 'empty' as const }, tasks: projectTasks },
};

const remoteChat = (id: string, name: string, path = '.') => ({
  ...chatItem, project_item_id: `remote-chat-${id}`, target_id: id, displayName: name,
  metadata: { source_id: connectedSource.source_id, path },
  encrypted: { ...chatItem.encrypted, project_item_id: `remote-chat-${id}` },
});
const remoteChats = [remoteChat(chatItem.target_id, 'Website launch'), remoteChat('budget-chat', 'Budget review'), remoteChat('nested-chat', 'Q4 planning', 'Research/Q4'), remoteChat('planning-chat', 'Planning review', 'Research/Planning/Deep')];
const remoteChatPresentations = Object.fromEntries(remoteChats.map((chat) => [chat.target_id, { ...chatPresentation, title: chat.displayName }]));
const mixedRemoteEntries = [
  { path: 'architecture.pdf', kind: 'file' as const, sizeBytes: 1024 },
  { path: 'README.md', kind: 'file' as const, sizeBytes: 1024 },
  { path: 'Research', kind: 'directory' as const },
  { path: 'Research/Q4', kind: 'directory' as const },
  { path: 'Research/Q4/notes.md', kind: 'file' as const, sizeBytes: 200 },
];
const mixedRemoteProps = { ...overviewProps, initialTab: 'folders' as const,
  previewState: { ...overviewProps.previewState, items: remoteChats, sources: [connectedSource],
    remoteEntries: mixedRemoteEntries, chatPresentations: remoteChatPresentations } };
const pagedChats = [remoteChat('first-chat', 'A chat'), remoteChat('boundary-chat', 'remote-file-047.ts'), remoteChat('last-chat', 'z chat')];

export default overviewProps;
export const variants = {
  mixedRemoteChats: mixedRemoteProps,
  offlineRemoteChats: { ...mixedRemoteProps, previewState: { ...mixedRemoteProps.previewState,
    sources: [{ ...connectedSource, status: 'offline' as const, encrypted: { ...connectedSource.encrypted, status: 'offline' as const } }] } },
  pagedRemoteChats: { ...mixedRemoteProps, previewState: { ...mixedRemoteProps.previewState,
    items: pagedChats, remoteEntries: largeRemoteEntries,
    chatPresentations: Object.fromEntries(pagedChats.map((chat) => [chat.target_id, { ...chatPresentation, title: chat.displayName }])) } },
  chats: { ...overviewProps, previewState: { ...overviewProps.previewState, items: [...items, chatItem], chatPresentations: { [chatItem.target_id]: chatPresentation } } },
  landing: { ...overviewProps, previewState: { ...overviewProps.previewState, startAtHome: true } },
  folders: { ...overviewProps, initialTab: 'folders' as const },
  readme: {
    ...overviewProps,
    previewState: {
      ...overviewProps.previewState,
      readme: {
        status: 'ready' as const,
        document: {
          path: 'README.md' as const,
          origin: 'stored' as const,
          imageUrls: {},
          content: '# OpenMates\n\nA private workspace for planning, research, and shipping useful work.\n\n## What we are building\n\n- Calm collaboration\n- Useful project context\n- Clear next steps',
        },
      },
    },
  },
  tasks: { ...overviewProps, initialTab: 'tasks' as const },
  connectedSource: {
    ...overviewProps,
    initialTab: 'folders' as const,
    previewState: {
      ...overviewProps.previewState,
      sources: [connectedSource],
      remoteEntries: [
        { path: 'frontend', kind: 'directory' as const, children: [
          { path: 'frontend/src', kind: 'directory' as const },
          { path: 'frontend/app.ts', kind: 'file' as const },
        ], childFileCount: 1, childFolderCount: 1, childFileSizeBytes: 2048, childSummaryTruncated: false },
        { path: 'README.md', kind: 'file' as const, sizeBytes: 1024 },
      ],
    },
  },
  localFolderSource: {
    ...overviewProps,
    initialTab: 'folders' as const,
    previewState: {
      ...overviewProps.previewState,
      sources: [{
        ...connectedSource,
        source_type: 'local_folder' as const,
        encrypted: { ...connectedSource.encrypted, source_type: 'local_folder' as const },
      }],
      remoteEntries: [
        { path: 'frontend', kind: 'directory' as const },
        { path: 'README.md', kind: 'file' as const, sizeBytes: 1024 },
      ],
    },
  },
  multipleSources: {
    ...overviewProps,
    initialTab: 'folders' as const,
    previewState: {
      ...overviewProps.previewState,
      sources: [connectedSource, {
        ...connectedSource,
        source_id: 'source-second',
        displayName: 'Second repository',
        encrypted: { ...connectedSource.encrypted, source_id: 'source-second' },
      }],
      remoteEntries: [
        { path: 'docs', kind: 'directory' as const },
        { path: 'README.md', kind: 'file' as const, sizeBytes: 1024 },
      ],
    },
  },
  largeConnectedSource: {
    ...overviewProps,
    initialTab: 'folders' as const,
    previewState: {
      ...overviewProps.previewState,
      items: [...items, ...largeStoredItems, nestedStoredItem],
      sources: [connectedSource],
      remoteEntries: largeRemoteEntries,
    },
  },
  legacyConnectedSource: {
    ...overviewProps,
    initialTab: 'folders' as const,
    previewState: {
      ...overviewProps.previewState,
      sources: [connectedSource],
      // Emulates an older requester returning its entire 500-entry list for one
      // maxEntries=48 request, leaving ProjectsPage to bound the mounted page.
      legacyRemoteEntries,
    },
  },
  sidebar: { ...overviewProps, variant: 'sidebar' as const },
};
