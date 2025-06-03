// src/components/MessageInput/utils/urlHelpers.ts
import type { Editor } from "@tiptap/core";
/**
 * Formats a URL into its subdomain, domain, and path parts.
 */
export function formatUrlParts(url: string) {
    try {
        const urlObj = new URL(url);
        const parts = {
            subdomain: '',
            domain: '',
            path: ''
        };

        const hostParts = urlObj.hostname.split('.');
        if (hostParts.length > 2) {
            parts.subdomain = hostParts[0] + '.';
            parts.domain = hostParts.slice(1).join('.');
        } else {
            parts.domain = urlObj.hostname;
        }

        const fullPath = urlObj.pathname + urlObj.search + urlObj.hash;
        parts.path = fullPath === '/' ? '' : fullPath;

        return parts;
    } catch (error) {
        console.error('Error formatting URL:', error);
        return {
            subdomain: '',
            domain: url,
            path: ''
        };
    }
}

/**
 * Detects URLs in the editor content and triggers replacement with web previews.
 *  The actual replacement is handled within the `WebPreview` extension and
 * the editor's `onUpdate` handler.
 *
 * @param editor The TipTap editor instance.
 * @param content The current editor content as a string (not used directly here).
 */
export function detectAndReplaceUrls(editor: Editor, content: string) {
    if (!editor) return;
      // Add URL detection regex
        const urlRegex = /https?:\/\/[^\s]+\.[a-z]{2,}(?:\/[^\s]*)?/gi;

        // Update YouTube regex to capture more formats
        const youtubeRegex = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|v\/|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
        // Get current cursor position
        const { from } = editor.state.selection;

        // Get the text content up to the cursor
        const text = editor.state.doc.textBetween(Math.max(0, from - 1000), from);

        // Only process if content ends with space or newline
        const lastChar = text.slice(-1);
        if (lastChar !== ' ' && lastChar !== '\n') return;

        // Find the last URL before the cursor
        const matches = Array.from(text.matchAll(urlRegex));
        if (!matches.length) return;

        // Get the last match
        const lastMatch = matches[matches.length - 1];
        const url = lastMatch[0];

        // Calculate absolute positions
        const matchStart = from - text.length + lastMatch.index!;
        const matchEnd = matchStart + url.length;

        // Check if this URL is already a preview
        const nodeAtPos = editor.state.doc.nodeAt(matchStart);
        // Updated to check for webEmbed
        if (nodeAtPos?.type.name === 'webEmbed' || nodeAtPos?.type.name === 'customEmbed' || nodeAtPos?.type.name === 'videoEmbed') return;

        // Check if it's a YouTube URL
        const youtubeMatch = url.match(youtubeRegex);
        if (youtubeMatch) {
            const videoId = youtubeMatch[1];
            // Use HD thumbnail by default
            const thumbnailUrl = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;

            // Replace URL with video preview node
            editor
                .chain()
                .focus()
                .deleteRange({ from: matchStart, to: matchEnd })
                .insertContent({
                    type: 'videoEmbed',
                    attrs: {
                        type: 'video',
                        src: url,
                        filename: url, // Use the full URL instead of "YouTube Video"
                        id: crypto.randomUUID(),
                        thumbnailUrl: thumbnailUrl,
                        isYouTube: true,
                        videoId: videoId,
                        duration: '--:--'
                    }
                })
                .run();
        } else {
            // Handle regular URLs as before
            editor
                .chain()
                .focus()
                .deleteRange({ from: matchStart, to: matchEnd })
                .insertContent({
                    type: 'webEmbed', // Changed to webEmbed
                    attrs: {
                        url,
                        id: crypto.randomUUID()
                    }
                })
                .run();
        }
}
