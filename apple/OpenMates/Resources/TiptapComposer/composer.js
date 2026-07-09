import { Editor } from './vendor/tiptap-core.mjs';
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

  function post(type, payload) {
    const body = Object.assign({ type }, payload || {});
    if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openmatesComposer) {
      window.webkit.messageHandlers.openmatesComposer.postMessage(body);
    }
  }

  function normalizeText(text) {
    return String(text || '').replace(/\u00a0/g, ' ');
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
    const lines = normalizeText(text).split('\n');
    return {
      type: 'doc',
      content: lines.length
        ? lines.map(function (line) {
            return line
              ? { type: 'paragraph', content: [{ type: 'text', text: line }] }
              : { type: 'paragraph' };
          })
        : [{ type: 'paragraph' }],
    };
  }

  function renderText(text) {
    if (!editor) return;
    suppressInput = true;
    editor.commands.setContent(textToDoc(text), { emitUpdate: false });
    currentText = readText();
    suppressInput = false;
    reportHeight();
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
    post('contentChanged', { text });
    reportHeight();
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
      default:
        post('error', { message: 'Unknown command: ' + command.type });
    }
  }

  window.OpenMatesComposer = { receive };

  editor = new Editor({
    element: editorElement,
    extensions: [
      StarterKit,
      Placeholder.configure({
        placeholder: function () { return placeholderText; },
        emptyEditorClass: 'is-editor-empty',
        emptyNodeClass: 'is-empty',
      }),
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

  document.addEventListener('selectionchange', reportHeight);
  setDisabled(false);
  applyPlaceholder();
  reportHeight();
  post('ready', { text: currentText, height: pendingHeight });
})();
