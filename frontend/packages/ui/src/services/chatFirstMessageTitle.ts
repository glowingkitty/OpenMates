/**
 * Loads the first-message display title for a chat that has no generated title
 * yet (rule: `utils/chatDisplayTitle.ts`). Messages come from the local
 * IndexedDB copy, which `chatDB` decrypts client-side with the chat key; the
 * result is held in memory only and never persisted or sent to the server.
 * Entries are keyed by the account/team workspace identity, so a logout,
 * account switch or team switch never serves another identity's text.
 *
 * Project mentions in the first message, drafts and previews are shown by the
 * Project's decrypted name, read from the local Project cache or the Project
 * itself; the names are held in memory with the same workspace keying.
 */
import { writable } from 'svelte/store';
import { chatDB } from './db';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { firstMessageDisplayTitle, mentionedProjectIds } from '../utils/chatDisplayTitle';
import { registerMentionProjectNameLookup, registerMentionProjectNameResolver } from '../utils/mentionProjectNames';

const MAX_ENTRIES = 256;
const firstMessageTitles = new Map<string, string>();
const projectNames = new Map<string, string>();
const pendingProjectNames = new Map<string, Promise<void>>();

// The Project service is loaded only once a Project mention needs a name, so
// chat-list and title code does not pull it (and its stores) in eagerly.
type ProjectServiceModule = typeof import('./projectService');
let projectServiceModule: ProjectServiceModule | null = null;
async function loadProjectService(): Promise<ProjectServiceModule> {
    projectServiceModule ??= await import('./projectService');
    return projectServiceModule;
}

/** Bumps whenever a Project name for a mention becomes known, so sync titles can re-derive. */
export const mentionProjectNamesVersion = writable(0);

function workspaceKey(id: string): string {
    return `${getWorkspaceCacheIdentity() ?? 'guest'}|${id}`;
}

function remember<T>(map: Map<string, T>, key: string, value: T): void {
    if (map.size >= MAX_ENTRIES) map.clear();
    map.set(key, value);
}

/** A mentioned Project's name when this device already knows it. */
export function knownMentionProjectName(projectId: string): string | undefined {
    return projectNames.get(workspaceKey(projectId))
        ?? projectServiceModule?.peekProjects()?.find((project) => project.project_id === projectId)?.name;
}

// Every draft, preview and title formatter shows mentioned Projects by these names.
registerMentionProjectNameLookup(knownMentionProjectName);
registerMentionProjectNameResolver((projectIds) => resolveProjectNames(projectIds));

/**
 * Looks up the names of the Projects mentioned in `content`. Projects this
 * account cannot open keep the generic "Project" label in the title.
 */
export async function resolveMentionProjectNames(content: string | null | undefined, teamId?: string | null): Promise<void> {
    await resolveProjectNames(mentionedProjectIds(content), teamId);
}

/** Fetches the names of the given Projects that this device does not know yet. */
async function resolveProjectNames(projectIds: string[], teamId?: string | null): Promise<void> {
    if (!projectIds.length) return;
    const { getProject } = await loadProjectService();
    const missing = projectIds.filter((projectId) => !knownMentionProjectName(projectId));
    await Promise.all(missing.map((projectId) => {
        const key = workspaceKey(projectId);
        let pending = pendingProjectNames.get(key);
        if (!pending) {
            pending = getProject(projectId, teamId === undefined ? {} : { teamId })
                .then((project) => {
                    if (!project.name?.trim()) return;
                    remember(projectNames, key, project.name.trim());
                    mentionProjectNamesVersion.update((version) => version + 1);
                })
                .catch((error: unknown) => {
                    console.debug('[chatFirstMessageTitle] Mentioned Project is not readable here:', error);
                })
                .finally(() => pendingProjectNames.delete(key));
            pendingProjectNames.set(key, pending);
        }
        return pending;
    }));
}

/** The first user message's readable beginning, or null when the chat has none. */
export async function loadFirstMessageDisplayTitle(chatId: string): Promise<string | null> {
    const key = workspaceKey(chatId);
    const known = firstMessageTitles.get(key);
    if (known) return known;
    const messages = await chatDB.getMessagesForChat(chatId);
    const firstContent = messages.find((message) => message.role === 'user')?.content;
    if (mentionedProjectIds(typeof firstContent === 'string' ? firstContent : '').length) {
        const chat = await chatDB.getChat(chatId);
        await resolveMentionProjectNames(firstContent as string, chat?.team_id);
    }
    const title = firstMessageDisplayTitle(messages, knownMentionProjectName);
    if (!title) return null;
    remember(firstMessageTitles, key, title);
    return title;
}
