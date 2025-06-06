// src/components/MessageInput/extensions/embeds/CodeEmbed.ts

import { Node, mergeAttributes, InputRule, PasteRule } from '@tiptap/core'; // Added InputRule, PasteRule
import { mountComponent } from '../../utils/editorHelpers';
import Code from '../../in_message_previews/Code.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';
import { Plugin, PluginKey } from 'prosemirror-state';
import { isLikelyCode, detectLanguage } from '../../utils/codeHelpers';

export interface CodeOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        codeEmbed: {
            setCodeEmbed: (options: {src: string; filename: string; id: string; language?: string; content?:string}) => ReturnType
        }
    }
}

export const CodeEmbed = Node.create<CodeOptions>({
    name: 'codeEmbed',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            src: {
                default: null,
            },
            filename: {
                default: null,
            },
            originalFilepath: { // To store the full matched filepath line
                default: null,
            },
            id: {
                default: () => crypto.randomUUID(),
            },
            language: {
                default: null,
            },
            content: { //for text directly added
                default: null,
            }
        };
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-code-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-code-embed': true })];
    },

    addProseMirrorPlugins() {
        const plugin = new Plugin({
            key: new PluginKey('codeEmbedPaste'),
            props: {
                handlePaste: (view, event, slice) => {
                    const textContent = event.clipboardData?.getData('text/plain');
                    if (!textContent) return false;

                    // If it's a large text but not code, let the TextEmbed handle it
                    if (textContent.length > 500 && !isLikelyCode(textContent)) {
                        return false;
                    }

                    if (isLikelyCode(textContent)) {
                        event.preventDefault();
                        const detectedLanguage = detectLanguage(textContent);
                        const blob = new Blob([textContent], { type: 'text/plain' });
                        const url = URL.createObjectURL(blob);

                        const { from } = view.state.selection;
                        
                        view.dispatch(view.state.tr.replaceWith(
                            from,
                            from,
                            this.type.create({
                                src: url,
                                filename: 'Code snippet',
                                language: detectedLanguage,
                                id: crypto.randomUUID(),
                                content: textContent
                            })
                        ));

                        // Insert a space after the code embed
                        view.dispatch(view.state.tr.insertText(' ', from + 1));
                        
                        return true; // Prevent further paste handling
                    }
                    
                    return false; // Allow default paste handling for non-code content
                },
            },
        });

        return [plugin];
    },

    addInputRules() {
        return [
            new InputRule({
                // Updated regex to match optional 'Filepath:' or 'filepath:' (case-insensitive), optional markdown bold/italics, and optional backticks around filename
                // Group 1: Filepath line (with or without backticks, with or without Filepath: prefix)
                // Group 2: language (optional)
                // Group 3: content
                find: /(?:(?:^|\n)\s*(?:[*_~]*)(?:[Ff]ilepath:)?\s*`?([a-zA-Z0-9_.\-\/\\]+\.[a-zA-Z0-9_.\-\/\\]+)`?(?:[*_~]*)\s*:?\s*\n)?```([a-zA-Z0-9_+\-#.,\s]*)\n([\s\S]*?\n)```$/,
                handler: ({ state, range, match }) => {
                    console.log('[CodeEmbed] InputRule triggered:', match);
                    const { tr } = state;
                    const potentialFilepathLine = (match[1] || '').trim();
                    const language = (match[2] || '').trim();
                    const content = (match[3] || '').replace(/\n$/, '').trim();
                    
                    let filename = 'Code snippet';
                    let originalFilepath: string | null = null;

                    if (potentialFilepathLine) {
                        originalFilepath = potentialFilepathLine.replace(/:$/, '');
                        const pathParts = originalFilepath.split(/[\/\\]/);
                        filename = pathParts.pop() || 'Code snippet';
                    }

                    const { from, to } = range;
                    tr.delete(from, to);
                    tr.insert(from, this.type.create({
                        language,
                        content,
                        filename,
                        originalFilepath,
                        id: crypto.randomUUID()
                    }));
                },
            }),
        ];
    },

    addPasteRules() {
        return [
            new PasteRule({
                // Updated regex to match optional 'Filepath:' or 'filepath:' (case-insensitive), optional markdown bold/italics, and optional backticks around filename
                // Group 1: Filepath line (with or without backticks, with or without Filepath: prefix)
                // Group 2: language (optional)
                // Group 3: content
                find: /(?:(?:^|\n)\s*(?:[*_~]*)(?:[Ff]ilepath:)?\s*`?([a-zA-Z0-9_.\-\/\\]+\.[a-zA-Z0-9_.\-\/\\]+)`?(?:[*_~]*)\s*:?\s*\n)?```([a-zA-Z0-9_+\-#.,\s]*)\n([\s\S]*?)\n```/g,
                handler: ({ state, range, match, chain }) => {
                    console.log('[CodeEmbed] PasteRule triggered:', match);
                    const potentialFilepathLine = (match[1] || '').trim();
                    const language = (match[2] || '').trim();
                    const content = (match[3] || '').trim();
                    
                    let filename = 'Pasted snippet';
                    let originalFilepath: string | null = null;

                    if (potentialFilepathLine) {
                        originalFilepath = potentialFilepathLine.replace(/:$/, '');
                        const pathParts = originalFilepath.split(/[\/\\]/);
                        filename = pathParts.pop() || 'Pasted snippet';
                    }

                    const { from, to } = range;
                    chain()
                        .deleteRange({ from, to })
                        .insertContentAt(from, {
                            type: this.name,
                            attrs: {
                                language,
                                content,
                                filename,
                                originalFilepath,
                                id: crypto.randomUUID(),
                            },
                        })
                        .run();
                },
            }),
        ];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-code-embed', 'true');

            let component: SvelteComponent | null = null;
            component = mountComponent(Code, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                language: node.attrs.language,
                content: node.attrs.content,
            });

            // Fixed event listener type
            dom.addEventListener('codefullscreen', ((event: Event) => {
                const customEvent = new CustomEvent('codefullscreen', {
                    detail: (event as CustomEvent).detail,
                    bubbles: true,
                    composed: true
                });
                dom.dispatchEvent(customEvent);
            }) as EventListener);

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
                        return false;
                    }

                    component?.$set({
                        src: updatedNode.attrs.src,
                        filename: updatedNode.attrs.filename,
                        id: updatedNode.attrs.id,
                        language: updatedNode.attrs.language,
                        content: updatedNode.attrs.content
                    });
                    return true;
                },
                destroy: () => {
                    component?.$destroy();
                    component = null;
                }
            };
        };
    },
     addCommands() {
        return {
            setCodeEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    },
    addKeyboardShortcuts() {
        return {
            Backspace: ({ editor }) => {
                const { empty, $anchor } = editor.state.selection;
                if (!empty) return false;

                const pos = $anchor.pos;
                const node = editor.state.doc.nodeAt(pos - 1);

                if (node?.type.name === this.name) {
                    const { originalFilepath: nodeOriginalFilepath, language: nodeLanguage = '', content: nodeContent = '' } = node.attrs;
                    const nodeStartPos = pos - node.nodeSize;

                    const tiptapContentPayload: any[] = [];

                    // Part 0 (Optional): Prepend original filepath if it exists
                    if (nodeOriginalFilepath) {
                        // Add a single newline before the restored filepath
                        tiptapContentPayload.push({ type: 'hardBreak' }); 
                        tiptapContentPayload.push({ type: 'text', text: nodeOriginalFilepath });
                        tiptapContentPayload.push({ type: 'hardBreak' }); // HardBreak after the filepath
                    }

                    // Part 1: The opening ```lang
                    tiptapContentPayload.push({
                        type: 'text',
                        text: `\`\`\`${nodeLanguage}`,
                    });
                    // Add a hardBreak after ```lang (this represents the first newline)
                    tiptapContentPayload.push({ type: 'hardBreak' });

                    // Part 2: The actual code content, with its internal newlines as hardBreaks
                    if (nodeContent) {
                        const lines = nodeContent.split('\n');
                        lines.forEach((line, index) => {
                            tiptapContentPayload.push({ type: 'text', text: line });
                            // Add a hardBreak for every newline that separated lines in the original content
                            if (index < lines.length - 1) {
                                tiptapContentPayload.push({ type: 'hardBreak' });
                            }
                        });
                    }
                    
                    // Part 3: Ensure the cursor is on a new line after all content,
                    // ready for the user to type the closing ``` or more code.
                    // This hardBreak represents the newline the cursor will be on.
                    tiptapContentPayload.push({ type: 'hardBreak' });

                    const revertFrom = nodeStartPos;
                    const revertTo = pos;

                    const textImmediatelyBeforeNode = editor.state.doc.textBetween(Math.max(0, revertFrom - 1), revertFrom);
                    const deleteFromPosition = (textImmediatelyBeforeNode === ' ') ? revertFrom - 1 : revertFrom;
                    
                    editor
                        .chain()
                        .focus()
                        .deleteRange({ from: deleteFromPosition, to: revertTo })
                        .insertContentAt(deleteFromPosition, tiptapContentPayload)
                        // Let Tiptap manage cursor placement after inserting complex content.
                        // It usually places it at the end of the inserted content.
                        .run();

                    return true;
                }
                return false;
            }
        };
    }
});
