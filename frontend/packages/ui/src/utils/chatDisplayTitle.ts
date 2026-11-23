/**
 * Display-only chat title rule shared by every surface that shows a chat title
 * (chat header, sidebar rows, start-screen cards).
 *
 * While a chat has no generated title yet, its title is the beginning of the
 * user's first message; once the preprocessor's title arrives it replaces it.
 * "Untitled chat" is never shown for a chat that has a user message.
 *
 * The fallback is readable text only: mention tokens in the message
 * (`@project:<id>:read`, `@focus:<app>:<focus>`, …) become their display names
 * (the Project name, the Focus title, …), privacy placeholders use the message
 * view's short alias ([PERSON_NAME_1]) and no identifier is ever shown.
 *
 * The fallback comes from message text that the client already decrypted
 * locally. It is never stored, encrypted into chat metadata, or sent anywhere.
 */
import { formatDraftPreview } from './draftPreview';
import { aliasEnhancedPlaceholders } from '../services/piiDisplayAliases';
import { mentionedProjectIds, type ProjectNameLookup } from './mentionDisplay';

export { mentionedProjectIds, type ProjectNameLookup };

/** Longest first-message prefix used as a display title. */
export const FIRST_MESSAGE_TITLE_MAX_LENGTH = 80;

type TitleSourceMessage = { role?: string | null; content?: unknown };

/**
 * Message text as a readable title: mentions become display names, embeds become
 * labels, and no mention syntax or identifier is left.
 */
export function readableTitleText(value: string | null | undefined, projectName?: ProjectNameLookup): string {
    // Privacy placeholders read as in the message view: [PERSON_NAME_1], never with their nonce.
    return aliasEnhancedPlaceholders(formatDraftPreview(value, projectName));
}

/** The readable beginning of the first user message, or '' when there is none. */
export function firstMessageDisplayTitle(
    messages: ReadonlyArray<TitleSourceMessage> | null | undefined,
    projectName?: ProjectNameLookup,
): string {
    const firstUserMessage = messages?.find((message) => message.role === 'user');
    return typeof firstUserMessage?.content === 'string'
        ? readableTitleText(firstUserMessage.content, projectName).slice(0, FIRST_MESSAGE_TITLE_MAX_LENGTH).trim()
        : '';
}

/** The generated title when present, else the first-message fallback, else null. */
export function resolveChatDisplayTitle(
    generatedTitle: string | null | undefined,
    firstMessageTitle: string | null | undefined,
): string | null {
    return generatedTitle?.trim() || firstMessageTitle?.trim() || null;
}
