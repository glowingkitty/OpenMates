<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import { isDesktop } from '../utils/platform';

  const dispatch = createEventDispatcher();

  // Track if this is the first instance to register global listener
  // This prevents multiple KeyboardShortcuts instances from registering duplicate listeners
  let isGlobalListenerRegistered = false;

  onMount(() => {
    const desktop = isDesktop();

    /**
     * Handle keyboard shortcuts with event capturing
     * Note: Some browser shortcuts (like Cmd+N, Cmd+Shift+N) may be captured
     * by the browser before reaching this handler. We use capture phase and
     * preventDefault() to try to override them, but success depends on the browser.
     */
    const handleKeyDown = (event: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      // Improved check for focused input: look for textarea, contenteditable, or ProseMirror class
      // This catches TipTap editors which create contenteditable divs
      const activeElement = document.activeElement;
      const isInputFocused = activeElement?.tagName.toLowerCase() === 'textarea' || 
                            activeElement?.getAttribute('contenteditable') === 'true' ||
                            activeElement?.classList.contains('ProseMirror');

      // Log all keydown events for debugging
      console.debug('[KeyboardShortcuts] keydown event:', {
        key: event.key,
        code: event.code,
        shiftKey: event.shiftKey,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        isInputFocused,
        activeElement: document.activeElement?.tagName,
        activeClass: document.activeElement?.className,
        contenteditable: document.activeElement?.getAttribute('contenteditable')
      });

      // IMPORTANT: Handle Shift+Enter FIRST before the blanket Enter ignore
      // This is a special case that should focus the input field
      if (event.shiftKey && event.key === 'Enter') {
        if (!isInputFocused) {
          event.preventDefault();
          event.stopPropagation();
          dispatch('focusInput');
          // Also dispatch as window event for fallback (reaches all listeners including parent components)
          window.dispatchEvent(new Event('focusInput'));
          return; // Exit early after handling
        }
      }

      // Explicitly ignore plain 'Enter' key to prevent interference with editor's native behavior
      // BUT allow Shift+Enter to pass through (handled above)
      if (event.key === 'Enter' && !event.shiftKey) {
        console.debug('[KeyboardShortcuts] Plain Enter key ignored (editor handles this)');
        return;
      }

      // MODERN COMMAND PALETTE: Ctrl/Cmd + K
      // Press K while holding Ctrl/Cmd to open command mode
      if ((isMac ? event.metaKey : event.ctrlKey) && event.key === 'k') {
        console.debug('[KeyboardShortcuts] Ctrl/Cmd+K detected (command palette mode)');
        event.preventDefault();
        event.stopPropagation();
        
        // Set flag that we're in command mode - listen for next key
        const nextKeyHandler = (nextEvent: KeyboardEvent) => {
          const nextKey = nextEvent.key.toUpperCase();
          console.debug('[KeyboardShortcuts] Command palette next key:', nextKey);
          
          // N = New Chat
          if (nextKey === 'N') {
            console.info('[KeyboardShortcuts] Command K+N detected (new chat)');
            nextEvent.preventDefault();
            nextEvent.stopPropagation();
            dispatch('newChat');
            window.removeEventListener('keydown', nextKeyHandler, true);
            return;
          }
          
          // ESC = Cancel command mode
          if (nextKey === 'ESCAPE') {
            console.debug('[KeyboardShortcuts] Command palette cancelled');
            nextEvent.preventDefault();
            window.removeEventListener('keydown', nextKeyHandler, true);
            return;
          }
          
          // Any other key cancels command mode
          console.debug('[KeyboardShortcuts] Command palette cancelled by key:', nextKey);
          window.removeEventListener('keydown', nextKeyHandler, true);
        };
        
        // Listen for the next key press with a timeout (cancel after 2 seconds)
        window.addEventListener('keydown', nextKeyHandler, true);
        setTimeout(() => {
          window.removeEventListener('keydown', nextKeyHandler, true);
          console.debug('[KeyboardShortcuts] Command palette timeout - cancelled');
        }, 2000);
        return;
      }

      // Download current chat: Ctrl/Cmd + Shift + S
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 's') {
        console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+S detected (download chat)');
        event.preventDefault();
        event.stopPropagation();
        console.info('[KeyboardShortcuts] Dispatching downloadChat event');
        dispatch('downloadChat');
        // Also dispatch as window event for fallback
        window.dispatchEvent(new Event('downloadChat'));
        return;
      }

      // Copy current chat: Ctrl/Cmd + Shift + C
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 'c') {
        console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+C detected (copy chat)');
        event.preventDefault();
        event.stopPropagation();
        console.info('[KeyboardShortcuts] Dispatching copyChat event');
        dispatch('copyChat');
        // Also dispatch as window event for fallback
        window.dispatchEvent(new Event('copyChat'));
        return;
      }

      // Toggle chat history: Ctrl/Cmd + Shift + H
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 'h') {
        console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+H detected (toggle chat history)');
        event.preventDefault();
        event.stopPropagation();
        console.info('[KeyboardShortcuts] Dispatching toggleChatHistory event');
        dispatch('toggleChatHistory');
        // Also dispatch as window event for fallback
        window.dispatchEvent(new Event('toggleChatHistory'));
        return;
      }

      // Update scroll shortcuts to require Shift key
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey) {
        if (event.key === 'ArrowUp') {
          console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+ArrowUp (scroll to top)');
          event.preventDefault();
          dispatch('scrollToTop');
        } else if (event.key === 'ArrowDown') {
          console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+ArrowDown (scroll to bottom)');
          event.preventDefault();
          dispatch('scrollToBottom');
        }
      }

      // Chat navigation shortcuts: Ctrl/Cmd + Shift + Arrow keys
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey) {
        if (event.key === 'ArrowRight') {
          console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+ArrowRight (next chat)');
          event.preventDefault();
          dispatch('nextChat');
        } else if (event.key === 'ArrowLeft') {
          console.debug('[KeyboardShortcuts] Ctrl/Cmd+Shift+ArrowLeft (previous chat)');
          event.preventDefault();
          dispatch('previousChat');
        }
      }
    };

    // IMPORTANT: Only register the global listener ONCE, even if multiple KeyboardShortcuts components exist
    // Check if listener is already registered via a data attribute on window
    if (!(window as any).__keyboardShortcutsListenerRegistered) {
      console.info('[KeyboardShortcuts] Registering global keyboard listener (first instance)');
      window.addEventListener('keydown', handleKeyDown, true);
      (window as any).__keyboardShortcutsListenerRegistered = true;
      
      return () => {
        // Only remove listener if this was the registering instance
        console.info('[KeyboardShortcuts] Removing global keyboard listener');
        window.removeEventListener('keydown', handleKeyDown, true);
        (window as any).__keyboardShortcutsListenerRegistered = false;
      };
    } else {
      console.debug('[KeyboardShortcuts] Global keyboard listener already registered, skipping duplicate');
      return () => {
        // No-op for non-first instances
      };
    }
  });
</script>

<!-- No HTML needed, as this component only handles events -->
