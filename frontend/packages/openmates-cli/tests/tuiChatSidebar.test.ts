import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { createInitialTuiState } from '../src/tuiRenderer.js';
import { tuiChatSidebarRows, tuiChatBreadcrumb, updateTuiChatSidebar, refreshTuiChatSidebar } from '../src/tuiChatSidebar.js';
import { renderWorkspaceFrame } from '../src/tuiLayout.js';
import { cells } from '../src/tuiText.js';
const hash = (id: string) => createHash('sha256').update(id).digest('hex');
function fixture() {
  const state = createInitialTuiState(); state.signedIn = true; state.sidebarOpen = true; state.focus = 'sidebar';
  state.recentChats = [{ id: 'parent', title: 'Research' }, { id: 'idle', title: 'Idle chat' }] as typeof state.recentChats;
  state.activityChats = [{ id: 'middle', parentId: 'parent' }, { id: 'child', parentId: 'middle' }] as typeof state.activityChats;
  state.runningChatIds = ['child'];
  state.sidebarLinkedChats = [{ id: 'older-chat', title: null, isHiddenCandidate: false }] as typeof state.sidebarLinkedChats;
  state.chatSidebarProjects = [{ id: 'launch', name: 'Website launch',
    folders: [{ id: 'marketing', name: 'Marketing', parentHash: null }, { id: 'campaigns', name: 'Campaigns', parentHash: hash('marketing') },
      { id: 'copy', name: 'Launch copy', parentHash: hash('campaigns') }],
    items: [{ id: 'link', type: 'chat', targetId: 'middle', folderId: 'copy', name: 'Research branch' },
      { id: 'old', type: 'chat', targetId: 'older-chat', folderId: 'copy', name: 'Saved launch headlines' }],
  }] as typeof state.chatSidebarProjects;
  return state;
}

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running,chat-navigation.projects.nested-readable
test('running descendants stay first and all containing folders spin at any depth', () => {
  const state = fixture();
  assert.equal(tuiChatSidebarRows(state)[0].chatId, 'parent');
  assert.equal(tuiChatSidebarRows(state).find(row => row.kind === 'project')?.running, true);
  state.chatSidebarLocation = { projectId: 'launch', folderId: 'marketing' };
  assert.equal(tuiChatSidebarRows(state)[0].chatId, 'parent');
  assert.equal(tuiChatSidebarRows(state).find(row => row.label === 'Campaigns')?.running, true);
  state.chatSidebarLocation.folderId = 'campaigns';
  assert.equal(tuiChatSidebarRows(state).find(row => row.label === 'Launch copy')?.running, true);
  assert.match(tuiChatBreadcrumb(state, 30)!, /Website launch › … › Campaigns/);
});

// contract-test: supporting surface=cli assertions=chat-navigation.projects.nested-readable
test('deep views include older linked chats and keep exact terminal bounds', () => {
  const state = fixture(); state.chatSidebarLocation = { projectId: 'launch', folderId: 'copy' };
  assert.ok(tuiChatSidebarRows(state).some(row => row.chatId === 'older-chat' && row.label === 'Saved launch headlines'));
  state.chatSidebarAncestors = true;
  assert.deepEqual(tuiChatSidebarRows(state).filter(row => row.kind === 'folder').map(row => row.label), ['Website launch', 'Marketing', 'Campaigns', 'Launch copy']);
  for (const width of [40, 72, 112]) {
    const frame = renderWorkspaceFrame(state, width, 24, ['Body'], { colorMode: 'none' });
    assert.equal(frame.split('\n').length, 24);
    assert.ok(frame.split('\n').every(row => cells(row) === width));
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running
test('activity completion and start preserve the selected chat identity', () => {
  const state = fixture(); state.sidebarIndex = tuiChatSidebarRows(state).findIndex(row => row.chatId === 'idle');
  updateTuiChatSidebar(state, () => { state.runningChatIds = []; });
  assert.equal(tuiChatSidebarRows(state)[state.sidebarIndex].chatId, 'idle');
  updateTuiChatSidebar(state, () => { state.runningChatIds = ['idle']; });
  assert.equal(state.sidebarIndex, 0); assert.equal(tuiChatSidebarRows(state)[0].chatId, 'idle');
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running
test('an activity response from the previous account cannot publish', async () => {
  const state = fixture(); let key = Buffer.alloc(32, 1);
  const client = { getActiveTeamId: () => null, getMasterKeyBytes: () => key,
    getChatActivity: async () => { key = Buffer.alloc(32, 2); return { ids: ['idle'], chats: [] }; } };
  await refreshTuiChatSidebar(state, client as never, () => {});
  assert.deepEqual(state.runningChatIds, ['child']);
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running,chat-navigation.projects.nested-readable
test('locked keys never expose rows, counts or saved project labels', () => {
  const state = fixture(); state.activityChats[1].isHiddenCandidate = true;
  state.sidebarLinkedChats[0].isHiddenCandidate = true;
  state.recentChats.push({ id: 'locked-recent', title: null, isHiddenCandidate: true } as never);
  let rows = tuiChatSidebarRows(state);
  assert.equal(rows.some(row => row.running), false);
  assert.equal(rows.some(row => row.chatId === 'locked-recent'), false);
  state.chatSidebarLocation = { projectId: 'launch', folderId: 'copy' };
  rows = tuiChatSidebarRows(state);
  assert.equal(rows.some(row => row.chatId === 'older-chat'), false);
  state.sidebarLinkedChats[0].isHiddenCandidate = false;
  assert.ok(tuiChatSidebarRows(state).some(row => row.label === 'Saved launch headlines'));
});
