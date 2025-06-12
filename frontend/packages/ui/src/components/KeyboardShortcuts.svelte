<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import { isDesktop } from '../utils/platform';

  const dispatch = createEventDispatcher();

  // State for space bar recording
  let spacebarPressStartTime: number | null = null;
  let spacebarHoldTimer: ReturnType<typeof setTimeout> | null = null;
  let isSpacebarRecording = false;

  onMount(() => {
    const desktop = isDesktop();

    const handleKeyDown = (event: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const isInputFocused = document.activeElement?.tagName.toLowerCase() === 'textarea' || 
                            document.activeElement?.classList.contains('ProseMirror');

      // Explicitly ignore 'Enter' key to prevent interference with editor's native behavior
      if (event.key === 'Enter') {
        return;
      }
      
      // Handle recording cancellation first
      if (spacebarPressStartTime && (event.key === 'Escape' || event.key === 'Backspace')) {
        event.preventDefault();
        dispatch('cancelRecording');
        resetSpacebarState();
        return;
      }

      // Only handle spacebar logic on desktop devices
      if (desktop && event.code === 'Space') {
        // On some mobile keyboards (e.g., Gboard), pressing 'Enter' can fire a 'Space' keycode.
        // We must also check the 'key' property to ensure we're not misinterpreting an Enter press.
        if (event.key === 'Enter') {
          return;
        }

        if (!isInputFocused) {
          return; // Exit early if input is not focused
        }
        
        if (!spacebarPressStartTime) {
          event.preventDefault(); // Prevent space only when starting a potential recording session
          spacebarPressStartTime = Date.now();
          
          // Set timer for long press (300ms)
          spacebarHoldTimer = setTimeout(() => {
            isSpacebarRecording = true;
            dispatch('startRecording');
          }, 300);
        }
        return;
      }

      // Existing shortcuts
      if ((isMac ? event.metaKey : event.ctrlKey) && event.key === 'n') {
        event.preventDefault();
        dispatch('newChat');
      }

      if (event.shiftKey && event.key === 'Enter') {
        if (!isInputFocused) {
          event.preventDefault();
          dispatch('focusInput');
        }
      }

      // Update scroll shortcuts to require Shift key
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey) {
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          dispatch('scrollToTop');
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          dispatch('scrollToBottom');
        }
      }

      // Add chat navigation shortcuts
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey) {
        if (event.key === 'ArrowRight') {
          event.preventDefault();
          dispatch('nextChat');
        } else if (event.key === 'ArrowLeft') {
          event.preventDefault();
          dispatch('previousChat');
        }
      }
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      // Only handle spacebar logic on desktop devices
      if (desktop && event.code === 'Space') {
        // Also check here to be absolutely sure we don't handle the keyup from a misinterpreted Enter press.
        if (event.key === 'Enter') {
          return;
        }

        const isInputFocused = document.activeElement?.tagName.toLowerCase() === 'textarea' || 
                              document.activeElement?.classList.contains('ProseMirror');
        
        // Always reset state if input is not focused
        if (!isInputFocused) {
          resetSpacebarState();
          return;
        }

        // Only proceed if we have a press start time (meaning we handled the keydown)
        if (!spacebarPressStartTime) {
          return;
        }

        const pressDuration = Date.now() - spacebarPressStartTime;
        
        if (spacebarHoldTimer) {
          clearTimeout(spacebarHoldTimer);
          spacebarHoldTimer = null;
        }

        // Only handle space insertion or recording stop if we're focused and haven't cancelled
        if (isInputFocused) {
          if (isSpacebarRecording) {
            dispatch('stopRecording');
          } else if (pressDuration < 300) {
            // This was a short press, not a recording.
            // We need to manually insert a space because we called preventDefault() on keydown.
            dispatch('insertSpace');
          }
        }

        resetSpacebarState();
      }
    };

    const resetSpacebarState = () => {
      spacebarPressStartTime = null;
      if (spacebarHoldTimer) {
        clearTimeout(spacebarHoldTimer);
        spacebarHoldTimer = null;
      }
      isSpacebarRecording = false;
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      if (spacebarHoldTimer) {
        clearTimeout(spacebarHoldTimer);
      }
    };
  });
</script>

<!-- No HTML needed, as this component only handles events -->
