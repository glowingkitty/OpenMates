// frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts

interface TiptapNode {
    type: string;
    attrs?: Record<string, any>;
    content?: TiptapNode[];
    text?: string;
    marks?: any[]; // Define more specifically if needed
}

interface TiptapDoc {
    type: 'doc';
    content: TiptapNode[];
}

// Regex for standalone URLs (simplified, adjust as needed for precision)
// This regex looks for URLs that are not already part of markdown links or image tags
const standaloneUrlRegex = /(?<!\]\()(?<!src=")(https?:\/\/[^\s]+\.[a-zA-Z]{2,}(\/\S*)?)/g;


// Regex for markdown code blocks
const markdownCodeBlockRegex = /```([a-zA-Z0-9_+\-#.]*?)\s*\n([\s\S]*?)\n```/g; // Refined regex for language capture

function processTextNodeForEmbeds(textNode: TiptapNode): TiptapNode[] {
    const newNodes: TiptapNode[] = [];
    let lastIndex = 0;
    let text = textNode.text || '';

    // IMPORTANT: If this text node already has a link mark, it's part of a markdown link [text](url)
    // Skip URL processing entirely to preserve the inline link format
    const hasLinkMark = textNode.marks && textNode.marks.some((mark: any) => mark.type === 'link');
    if (hasLinkMark) {
        // This is already a link - don't convert URLs to embeds
        return [textNode];
    }

    // First, process for code blocks as they are more distinct
    let match;
    while ((match = markdownCodeBlockRegex.exec(text)) !== null) {
        const [fullMatch, lang, codeContent] = match;
        const matchStart = match.index;
        const matchEnd = matchStart + fullMatch.length;

        // Add preceding text if any
        if (matchStart > lastIndex) {
            newNodes.push({ ...textNode, text: text.substring(lastIndex, matchStart) });
        }

        // Add code embed node using the correct schema
        newNodes.push({
            type: 'embed',
            attrs: {
                id: crypto.randomUUID(),
                type: 'code-code',
                status: 'finished',
                contentRef: null,
                language: (lang || '').trim(),
                filename: 'Code snippet', // Or derive from language
            },
        });
        lastIndex = matchEnd;
    }
    // Update text to the remainder after processing code blocks
    text = text.substring(lastIndex);
    lastIndex = 0; // Reset lastIndex for URL processing


    // Then, process the remaining text for URLs
    // Only process URLs that are not part of markdown links
    while ((match = standaloneUrlRegex.exec(text)) !== null) {
        const url = match[0];
        const matchStart = match.index;
        const matchEnd = matchStart + url.length;

        // Add preceding text if any
        if (matchStart > lastIndex) {
            newNodes.push({ ...textNode, text: text.substring(lastIndex, matchStart) });
        }
        
        // Add embed node using the correct schema
        // Basic check to avoid embedding YouTube URLs as generic web embed if they should be video embed
        const youtubeRegex = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|v\/|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
        if (!youtubeRegex.test(url)) {
             newNodes.push({
                type: 'embed',
                attrs: {
                    id: crypto.randomUUID(),
                    type: 'web-website',
                    status: 'finished',
                    contentRef: null,
                    url: url,
                },
            });
        } else {
            // If it's a YouTube URL, create a video embed
            newNodes.push({
                type: 'embed',
                attrs: {
                    id: crypto.randomUUID(),
                    type: 'videos-video',
                    status: 'finished',
                    contentRef: null,
                    url: url,
                },
            });
        }
       
        lastIndex = matchEnd;
    }

    // Add any remaining text
    if (lastIndex < text.length) {
        newNodes.push({ ...textNode, text: text.substring(lastIndex) });
    }
    
    // If no embeds were created, return the original text node in an array
    return newNodes.length > 0 ? newNodes : [textNode];
}


function traverseAndProcessNodes(nodes: TiptapNode[]): TiptapNode[] {
    const processedNodes: TiptapNode[] = [];
    for (const node of nodes) {
        if (node.type === 'text' && node.text) {
            processedNodes.push(...processTextNodeForEmbeds(node));
        } else {
            const newNode = { ...node };
            if (node.content) {
                newNode.content = traverseAndProcessNodes(node.content);
            }
            processedNodes.push(newNode);
        }
    }
    return processedNodes;
}

export function preprocessTiptapJsonForEmbeds(jsonContent: TiptapDoc | null | undefined): TiptapDoc | null | undefined {
    if (!jsonContent || jsonContent.type !== 'doc' || !jsonContent.content) {
        // console.debug('[preprocessTiptapJsonForEmbeds] Invalid or empty content, returning as is:', jsonContent);
        return jsonContent;
    }

    // console.debug('[preprocessTiptapJsonForEmbeds] Original content:', JSON.parse(JSON.stringify(jsonContent)));

    const processedContent = traverseAndProcessNodes(jsonContent.content);
    
    const result = {
        ...jsonContent,
        content: processedContent,
    };
    // console.debug('[preprocessTiptapJsonForEmbeds] Processed content:', JSON.parse(JSON.stringify(result)));
    return result;
}
