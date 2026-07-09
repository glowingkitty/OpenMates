import { Editor, Node, mergeAttributes } from './vendor/tiptap-core.mjs';
import StarterKit from './vendor/tiptap-starter-kit.mjs';
import Placeholder from './vendor/tiptap-placeholder.mjs';

(function () {
  'use strict';

  const editorElement = document.getElementById('message-editor');
  let editor;
  let currentText = '';
  let disabled = false;
  let compact = false;
  let pendingHeight = 0;
  let suppressInput = false;
  let placeholderText = '';

  const WEB_COMPOSER_EXTENSIONS = ['StarterKit', 'Placeholder', 'Embed'];
  const EMBED_COMMAND_NAMES = ['insertEmbed', 'updateEmbed', 'removeEmbed', 'serializeMarkdown', 'getDiagnostics'];

  const EmbedNode = Node.create({
    name: 'embed',
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
      return {
        id: { default: null },
        type: { default: 'file' },
        status: { default: 'finished' },
        contentRef: { default: null },
        uploadEmbedId: { default: null },
        filename: { default: null },
        duration: { default: null },
        transcript: { default: null },
        mimeType: { default: null },
        uploadError: { default: null },
        referenceType: { default: null },
      };
    },

    parseHTML() {
      return [{ tag: 'div[data-type="embed"]' }];
    },

    renderHTML({ HTMLAttributes }) {
      const attrs = embedAttrs(HTMLAttributes);
      return [
        'div',
        mergeAttributes(HTMLAttributes, {
          'data-type': 'embed',
          'data-testid': 'embed-full-width-wrapper',
          'data-embed-type': attrs.type,
          'data-embed-status': attrs.status,
          'data-embed-id': attrs.id,
          class: 'embed-full-width-wrapper',
          contenteditable: 'false',
        }),
        [
          'div',
          {
            class: 'embed-unified-container',
            'data-testid': 'embed-unified-container',
            'data-embed-type': attrs.type,
            'data-embed-status': attrs.status,
          },
          ['div', { class: 'embed-app-icon', 'aria-hidden': 'true' }, iconLabel(attrs.type)],
          [
            'div',
            { class: 'embed-content' },
            ['div', { class: 'embed-title' }, attrs.filename || titleForType(attrs.type)],
            ['div', { class: 'embed-subtitle' }, subtitleForEmbed(attrs)],
          ],
          ['button', { class: 'embed-remove', 'data-testid': 'editor-owned-embed-remove', 'data-embed-id': attrs.id, 'aria-label': 'Remove embed' }, 'x'],
        ],
      ];
    },
  });

  function post(type, payload) {
    const body = Object.assign({ type }, payload || {});
    if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openmatesComposer) {
      window.webkit.messageHandlers.openmatesComposer.postMessage(body);
    }
  }

  function normalizeText(text) {
    return String(text || '').replace(/\u00a0/g, ' ');
  }

  function embedAttrs(attrs) {
    return Object.assign({
      id: null,
      type: 'file',
      status: 'finished',
      contentRef: null,
      uploadEmbedId: null,
      filename: null,
      duration: null,
      transcript: null,
      mimeType: null,
      uploadError: null,
      referenceType: null,
    }, attrs || {});
  }

  function iconLabel(type) {
    if (type === 'recording' || type === 'audio-recording') return 'A';
    if (type === 'image' || type === 'images-image') return 'I';
    if (type === 'pdf') return 'P';
    if (type === 'maps' || type === 'location') return 'M';
    if (type === 'code-code' || type === 'code') return 'C';
    return 'F';
  }

  function titleForType(type) {
    switch (type) {
      case 'recording':
      case 'audio-recording':
        return 'Recording';
      case 'image':
      case 'images-image':
        return 'Image';
      case 'pdf':
        return 'PDF';
      case 'maps':
      case 'location':
        return 'Location';
      case 'code-code':
      case 'code':
        return 'Code';
      default:
        return 'Attachment';
    }
  }

  function subtitleForEmbed(attrs) {
    if (attrs.uploadError) return attrs.uploadError;
    if (attrs.transcript) return attrs.transcript;
    if (attrs.duration) return String(attrs.duration);
    if (attrs.status === 'uploading') return 'Uploading...';
    if (attrs.status === 'transcribing') return 'Transcribing...';
    if (attrs.status === 'error') return 'Upload failed';
    return attrs.status || 'finished';
  }

  function referenceTypeForEmbed(attrs) {
    if (attrs.referenceType) return attrs.referenceType;
    switch (attrs.type) {
      case 'recording':
      case 'audio-recording':
        return 'audio-recording';
      case 'image':
      case 'images-image':
        return 'image';
      case 'maps':
        return 'location';
      case 'code-code':
        return 'code';
      case 'docs-doc':
        return 'docs-doc';
      default:
        return attrs.type || 'file';
    }
  }

  function embedIdForReference(attrs) {
    if (attrs.contentRef && String(attrs.contentRef).startsWith('embed:')) {
      return String(attrs.contentRef).slice('embed:'.length);
    }
    return attrs.uploadEmbedId || attrs.id;
  }

  function serializeEmbed(attrs) {
    const normalized = embedAttrs(attrs);
    const embedId = embedIdForReference(normalized);
    if (!embedId) return '';
    const reference = {
      type: referenceTypeForEmbed(normalized),
      embed_id: embedId,
    };
    return '```json\n' + JSON.stringify(reference, null, 2) + '\n```';
  }

  function inlineText(nodes) {
    return (nodes || []).map(function (node) {
      if (node.type === 'hardBreak') return '\n';
      let text = normalizeText(node.text || '');
      for (const mark of node.marks || []) {
        if (mark.type === 'code') text = '`' + text.replace(/`/g, '\\`') + '`';
        if (mark.type === 'bold') text = '**' + text + '**';
        if (mark.type === 'italic') text = '*' + text + '*';
        if (mark.type === 'strike') text = '~~' + text + '~~';
        if (mark.type === 'link' && mark.attrs && mark.attrs.href) text = '[' + text + '](' + mark.attrs.href + ')';
      }
      return text;
    }).join('');
  }

  function serializeBlock(node, index) {
    switch (node.type) {
      case 'paragraph':
        return inlineText(node.content);
      case 'embed':
        return serializeEmbed(node.attrs);
      case 'heading':
        return '#'.repeat(Math.min(Math.max(node.attrs && node.attrs.level || 1, 1), 6)) + ' ' + inlineText(node.content);
      case 'blockquote':
        return serializeBlocks(node.content).split('\n').map(function (line) { return '> ' + line; }).join('\n');
      case 'codeBlock':
        return '```\n' + inlineText(node.content) + '\n```';
      case 'horizontalRule':
        return '---';
      case 'bulletList':
        return (node.content || []).map(function (item) { return '- ' + serializeBlocks(item.content).replace(/\n/g, '\n  '); }).join('\n');
      case 'orderedList': {
        const start = node.attrs && node.attrs.start || 1;
        return (node.content || []).map(function (item, offset) {
          return String(start + offset) + '. ' + serializeBlocks(item.content).replace(/\n/g, '\n   ');
        }).join('\n');
      }
      case 'listItem':
        return serializeBlocks(node.content);
      default:
        return inlineText(node.content) || (node.content ? serializeBlocks(node.content) : '');
    }
  }

  function serializeBlocks(nodes) {
    return (nodes || []).map(serializeBlock).filter(function (block, index, blocks) {
      return block.length > 0 || index < blocks.length - 1;
    }).join('\n\n');
  }

  function serializeMarkdown(doc) {
    if (!doc || !doc.content) return '';
    return serializeBlocks(doc.content).replace(/\n+$/, '');
  }

  function readText() {
    if (!editor) return '';
    return serializeMarkdown(editor.getJSON());
  }

  function textToDoc(text) {
    const normalized = normalizeText(text);
    const embedBlockPattern = /```json\n([\s\S]*?)\n```/g;
    const content = [];
    let lastIndex = 0;
    let match;

    function appendText(rawText) {
      const lines = rawText.split('\n');
      for (const line of lines) {
        if (line) {
          content.push({ type: 'paragraph', content: [{ type: 'text', text: line }] });
        } else if (content.length > 0) {
          content.push({ type: 'paragraph' });
        }
      }
    }

    while ((match = embedBlockPattern.exec(normalized)) !== null) {
      appendText(normalized.slice(lastIndex, match.index).replace(/\n+$/, ''));
      try {
        const parsed = JSON.parse(match[1].trim());
        if (parsed && parsed.embed_id) {
          content.push({
            type: 'embed',
            attrs: embedAttrs({
              id: parsed.embed_id,
              type: parsed.type || 'file',
              referenceType: parsed.type || 'file',
              status: 'finished',
              contentRef: 'embed:' + parsed.embed_id,
              filename: parsed.filename || null,
            }),
          });
        }
      } catch (_error) {
        appendText(match[0]);
      }
      lastIndex = match.index + match[0].length;
    }

    appendText(normalized.slice(lastIndex).replace(/^\n+/, ''));

    return {
      type: 'doc',
      content: content.length ? content : [{ type: 'paragraph' }],
    };
  }

  function embedNodes() {
    const nodes = [];
    if (!editor) return nodes;
    editor.state.doc.descendants(function (node, pos) {
      if (node.type.name === 'embed') {
        nodes.push({ node, pos, attrs: embedAttrs(node.attrs) });
      }
      return true;
    });
    return nodes;
  }

  function blockingEmbeds() {
    return embedNodes().filter(function (entry) {
      return entry.attrs.status === 'uploading' || entry.attrs.status === 'transcribing';
    });
  }

  function postDiagnostics(type) {
    const embeds = embedNodes();
    post(type, {
      text: currentText,
      embedCount: embeds.length,
      blockingEmbedCount: blockingEmbeds().length,
      extensions: WEB_COMPOSER_EXTENSIONS,
      embedCommandNames: EMBED_COMMAND_NAMES,
    });
  }

  function insertEmbed(command) {
    if (!editor) return;
    const attrs = embedAttrs(command.attrs || command.embed || command);
    if (!attrs.id) attrs.id = window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : String(Date.now());
    editor.chain().focus().insertContent([{ type: 'embed', attrs }, { type: 'paragraph' }]).run();
    post('embedInserted', { embedId: attrs.id, embedType: attrs.type, embedStatus: attrs.status });
    reportContentChanged();
    postDiagnostics('diagnostics');
  }

  function updateEmbed(command) {
    if (!editor || !command.id) return;
    const match = embedNodes().find(function (entry) { return entry.attrs.id === command.id || entry.attrs.uploadEmbedId === command.id; });
    if (!match) return;
    const attrs = embedAttrs(Object.assign({}, match.attrs, command.attrs || {}, command.status ? { status: command.status } : {}));
    const tr = editor.state.tr.setNodeMarkup(match.pos, undefined, attrs);
    editor.view.dispatch(tr);
    post('embedUpdated', { embedId: attrs.id, embedType: attrs.type, embedStatus: attrs.status });
    reportContentChanged();
    postDiagnostics('diagnostics');
  }

  function removeEmbed(command) {
    if (!editor || !command.id) return;
    const match = embedNodes().find(function (entry) { return entry.attrs.id === command.id || entry.attrs.uploadEmbedId === command.id; });
    if (!match) return;
    editor.chain().focus().deleteRange({ from: match.pos, to: match.pos + match.node.nodeSize }).run();
    post('embedRemoved', { embedId: match.attrs.id, embedType: match.attrs.type });
    reportContentChanged();
    postDiagnostics('diagnostics');
  }

  function renderText(text) {
    if (!editor) return;
    suppressInput = true;
    editor.commands.setContent(textToDoc(text), { emitUpdate: false });
    currentText = readText();
    suppressInput = false;
    reportHeight();
    postDiagnostics('diagnostics');
  }

  function reportHeight() {
    requestAnimationFrame(function () {
      const height = Math.ceil(editorElement.scrollHeight);
      if (height !== pendingHeight) {
        pendingHeight = height;
        post('heightChanged', { height });
      }
    });
  }

  function reportContentChanged() {
    if (suppressInput) return;
    const text = readText();
    if (text === currentText) {
      reportHeight();
      return;
    }
    currentText = text;
    const blockingCount = blockingEmbeds().length;
    post('contentChanged', { text, embedCount: embedNodes().length, blockingEmbedCount: blockingCount });
    post('blockingEmbedsChanged', { blockingEmbedCount: blockingCount });
    reportHeight();
  }

  function focusEditor() {
    if (!disabled && editor) editor.commands.focus('end');
  }

  function applyTheme(theme) {
    if (!theme) return;
    const root = document.documentElement.style;
    if (theme.fontPrimary) root.setProperty('--font-primary', theme.fontPrimary);
    if (theme.fontTertiary) root.setProperty('--font-tertiary', theme.fontTertiary);
    if (theme.buttonPrimary) root.setProperty('--button-primary', theme.buttonPrimary);
  }

  function setCompact(value) {
    compact = Boolean(value);
    editorElement.classList.toggle('inline-compact', compact);
    reportHeight();
  }

  function setDisabled(value) {
    disabled = Boolean(value);
    if (editor) editor.setEditable(!disabled);
    document.body.setAttribute('contenteditable', disabled ? 'false' : 'true');
  }

  function applyPlaceholder() {
    editorElement.setAttribute('data-placeholder', placeholderText);
    const emptyNode = editorElement.querySelector('.is-editor-empty');
    if (emptyNode) emptyNode.setAttribute('data-placeholder', placeholderText);
  }

  function receive(command) {
    if (!command || !command.type) return;
    switch (command.type) {
      case 'focus':
        if (!disabled && editor) editor.commands.focus('end');
        break;
      case 'blur':
        if (editor) editor.commands.blur();
        break;
      case 'clear':
        renderText('');
        post('contentChanged', { text: '' });
        break;
      case 'setContent':
        renderText(command.text || '');
        break;
      case 'setPlaceholder':
        placeholderText = command.placeholder || '';
        editorElement.setAttribute('aria-label', placeholderText || 'Message editor');
        applyPlaceholder();
        break;
      case 'setTheme':
        applyTheme(command.theme);
        break;
      case 'setCompact':
        setCompact(command.compact);
        break;
      case 'setDisabled':
        setDisabled(command.disabled);
        break;
      case 'insertEmbed':
        insertEmbed(command);
        break;
      case 'updateEmbed':
        updateEmbed(command);
        break;
      case 'removeEmbed':
        removeEmbed(command);
        break;
      case 'serializeMarkdown':
        post('serializedMarkdown', { text: readText(), embedCount: embedNodes().length, blockingEmbedCount: blockingEmbeds().length });
        break;
      case 'getDiagnostics':
        postDiagnostics('diagnostics');
        break;
      default:
        post('error', { message: 'Unknown command: ' + command.type });
    }
  }

  window.OpenMatesComposer = { receive };

  editor = new Editor({
    element: editorElement,
    extensions: [
      StarterKit.configure({
        hardBreak: { keepMarks: true, HTMLAttributes: {} },
        bold: false,
        italic: false,
        strike: false,
        code: false,
        heading: false,
        blockquote: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        horizontalRule: false,
        codeBlock: false,
        link: false,
      }),
      Placeholder.configure({
        placeholder: function () { return placeholderText; },
        emptyEditorClass: 'is-editor-empty',
        emptyNodeClass: 'is-empty',
      }),
      EmbedNode,
    ],
    content: textToDoc(''),
    autofocus: false,
    editable: true,
    injectCSS: false,
    editorProps: {
      attributes: {
        role: 'textbox',
        'aria-multiline': 'true',
        'data-testid': 'message-editor-prosemirror',
      },
      handleKeyDown: function (_view, event) {
        if (event.key === 'Enter' && !event.shiftKey && !event.altKey && !event.metaKey && !event.ctrlKey && !event.isComposing) {
          event.preventDefault();
          post('submit');
          return true;
        }
        return false;
      },
    },
    onUpdate: reportContentChanged,
    onFocus: function () { post('focus'); },
    onBlur: function () { post('blur'); },
    onTransaction: function () {
      applyPlaceholder();
      reportHeight();
    },
  });

  editorElement.addEventListener('click', focusEditor);
  editorElement.addEventListener('touchend', focusEditor);
  editorElement.addEventListener('click', function (event) {
    const target = event.target;
    if (target && target.matches && target.matches('[data-testid="editor-owned-embed-remove"]')) {
      event.preventDefault();
      removeEmbed({ id: target.getAttribute('data-embed-id') });
    }
  });
  editorElement.addEventListener('input', reportContentChanged, true);
  editorElement.addEventListener('keyup', reportContentChanged, true);
  document.addEventListener('selectionchange', reportHeight);
  setDisabled(false);
  applyPlaceholder();
  reportHeight();
  post('ready', { text: currentText, height: pendingHeight, embedCount: 0, blockingEmbedCount: 0, extensions: WEB_COMPOSER_EXTENSIONS, embedCommandNames: EMBED_COMMAND_NAMES });
})();
