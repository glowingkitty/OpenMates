<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import { isDesktop } from '../utils/platform';

  const dispatch = createEventDispatcher();

  // State for space bar recording (commented out - feature not yet implemented)
  // let spacebarPressStartTime: number | null = null;
  // let spacebarHoldTimer: ReturnType<typeof setTimeout> | null = null;
  // let isSpacebarRecording = false;

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
      const isInputFocused = document.activeElement?.tagName.toLowerCase() === 'textarea' || 
                            document.activeElement?.classList.contains('ProseMirror');

      // Explicitly ignore 'Enter' key to prevent interference with editor's native behavior
      if (event.key === 'Enter') {
        return;
      }
      
      // --- AUDIO RECORDING SHORTCUTS (Commented out - feature not yet implemented) ---
      // Handle recording cancellation first
      // if (spacebarPressStartTime && (event.key === 'Escape' || event.key === 'Backspace')) {
      //   event.preventDefault();
      //   dispatch('cancelRecording');
      //   resetSpacebarState();
      //   return;
      // }

      // Only handle spacebar logic on desktop devices
      // if (desktop && event.code === 'Space') {
      //   // On some mobile keyboards (e.g., Gboard), pressing 'Enter' can fire a 'Space' keycode.
      //   // We must also check the 'key' property to ensure we're not misinterpreting an Enter press.
      //   if (event.key === 'Enter') {
      //     return;
      //   }

      //   if (!isInputFocused) {
      //     return; // Exit early if input is not focused
      //   }
      //   
      //   if (!spacebarPressStartTime) {
      //     event.preventDefault(); // Prevent space only when starting a potential recording session
      //     spacebarPressStartTime = Date.now();
      //     
      //     // Set timer for long press (300ms)
      //     spacebarHoldTimer = setTimeout(() => {
      //       isSpacebarRecording = true;
      //       dispatch('startRecording');
      //     }, 300);
      //   }
      //   return;
      // }
      // --- END AUDIO RECORDING SHORTCUTS ---

      // Create new chat: Ctrl/Cmd + Shift + N
      // Using Shift + N to avoid conflict with browser's Ctrl/Cmd + N (new window)
      // Note: Some browsers (Arc, Chrome) may still capture this for incognito window
      // We call preventDefault() but browser may override - test in your browser
      if ((isMac ? event.metaKey : event.ctrlKey) && event.shiftKey && event.key === 'N') {
        event.preventDefault();
        event.stopPropagation(); // Also stop propagation to prevent bubbling
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

      // Chat navigation shortcuts: Ctrl/Cmd + Shift + Arrow keys
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

    // --- AUDIO RECORDING KEY UP HANDLER (Commented out - feature not yet implemented) ---
    // const handleKeyUp = (event: KeyboardEvent) => {
    //   // Only handle spacebar logic on desktop devices
    //   if (desktop && event.code === 'Space') {
    //     // Also check here to be absolutely sure we don't handle the keyup from a misinterpreted Enter press.
    //     if (event.key === 'Enter') {
    //       return;
    //     }

    //     const isInputFocused = document.activeElement?.tagName.toLowerCase() === 'textarea' || 
    //                           document.activeElement?.classList.contains('ProseMirror');
    //     
    //     // Always reset state if input is not focused
    //     if (!isInputFocused) {
    //       resetSpacebarState();
    //       return;
    //     }

    //     // Only proceed if we have a press start time (meaning we handled the keydown)
    //     if (!spacebarPressStartTime) {
    //       return;
    //     }

    //     const pressDuration = Date.now() - spacebarPressStartTime;
    //     
    //     if (spacebarHoldTimer) {
    //       clearTimeout(spacebarHoldTimer);
    //       spacebarHoldTimer = null;
    //     }

    //     // Only handle space insertion or recording stop if we're focused and haven't cancelled
    //     if (isInputFocused) {
    //       if (isSpacebarRecording) {
    //         dispatch('stopRecording');
    //       } else if (pressDuration < 300) {
    //         // This was a short press, not a recording.
    //         // We need to manually insert a space because we called preventDefault() on keydown.
    //         dispatch('insertSpace');
    //       }
    //     }

    //     resetSpacebarState();
    //   }
    // };

    // const resetSpacebarState = () => {
    //   spacebarPressStartTime = null;
    //   if (spacebarHoldTimer) {
    //     clearTimeout(spacebarHoldTimer);
    //     spacebarHoldTimer = null;
    //   }
    //   isSpacebarRecording = false;
    // };
    // --- END AUDIO RECORDING KEY UP HANDLER ---

    // Use capture phase (third parameter = true) to try to capture events before browser
    // This increases the chance of preventDefault() working for browser shortcuts
    window.addEventListener('keydown', handleKeyDown, true);
    // window.addEventListener('keyup', handleKeyUp, true); // Commented out - for audio recording

    return () => {
      window.removeEventListener('keydown', handleKeyDown, true);
      // window.removeEventListener('keyup', handleKeyUp, true); // Commented out - for audio recording
      // if (spacebarHoldTimer) {
      //   clearTimeout(spacebarHoldTimer);
      // }
    };
  });
</script>

<!-- No HTML needed, as this component only handles events -->
