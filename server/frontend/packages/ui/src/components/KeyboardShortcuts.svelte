<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher();

  // State for space bar recording
  let spacebarPressStartTime: number | null = null;
  let spacebarHoldTimer: ReturnType<typeof setTimeout> | null = null;
  let isSpacebarRecording = false;

  onMount(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const isInputFocused = document.activeElement?.tagName.toLowerCase() === 'textarea' || 
                            document.activeElement?.classList.contains('ProseMirror');

      // Handle recording cancellation first
      if (spacebarPressStartTime && (event.key === 'Escape' || event.key === 'Backspace')) {
        event.preventDefault();
        dispatch('cancelRecording');
        resetSpacebarState();
        return;
      }

      // Only handle spacebar logic when input is focused
      if (event.code === 'Space') {
        if (!isInputFocused) {
          return; // Exit early if input is not focused
        }

        event.preventDefault(); // Always prevent space from being typed during potential recording
        
        if (!spacebarPressStartTime) {
          spacebarPressStartTime = Date.now();
          
          // Set timer for long press (1000ms)
          spacebarHoldTimer = setTimeout(() => {
            isSpacebarRecording = true;
            dispatch('startRecording');
          }, 1000);
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
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space') {
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
        if (!event.defaultPrevented && isInputFocused) {
          if (pressDuration < 250 && !isSpacebarRecording) {
            dispatch('insertSpace');
          } else if (isSpacebarRecording) {
            dispatch('stopRecording');
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
