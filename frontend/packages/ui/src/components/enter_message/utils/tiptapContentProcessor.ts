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

        // Add CodeEmbed node
        newNodes.push({
            type: 'codeEmbed',
            attrs: {
                language: (lang || '').trim(),
                content: codeContent.trim(),
                filename: 'Code snippet', // Or derive from language
                id: crypto.randomUUID(),
            },
        });
        lastIndex = matchEnd;
    }
    // Update text to the remainder after processing code blocks
    text = text.substring(lastIndex);
    lastIndex = 0; // Reset lastIndex for URL processing


    // Then, process the remaining text for URLs
    while ((match = standaloneUrlRegex.exec(text)) !== null) {
        const url = match[0];
        const matchStart = match.index;
        const matchEnd = matchStart + url.length;

        // Add preceding text if any
        if (matchStart > lastIndex) {
            newNodes.push({ ...textNode, text: text.substring(lastIndex, matchStart) });
        }
        
        // Add WebEmbed node
        // Basic check to avoid embedding YouTube URLs as generic WebEmbed if they should be VideoEmbed
        // This might need more sophisticated handling if VideoEmbed also needs to be created from plain URLs here.
        const youtubeRegex = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|v\/|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
        if (!youtubeRegex.test(url)) {
             newNodes.push({
                type: 'webEmbed',
                attrs: {
                    url: url,
                    id: crypto.randomUUID(),
                },
            });
        } else {
            // If it's a YouTube URL, and we want to create a VideoEmbed here,
            // we'd need to add that logic. For now, just re-add it as text
            // or let a subsequent process handle it if VideoEmbeds are created differently.
            // For simplicity, re-adding as text if it's a YouTube URL to avoid conflict.
             newNodes.push({ ...textNode, text: url });
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
