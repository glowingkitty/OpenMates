<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';

  // Allow passing a custom style from the parent.
  export let style: string = "";

  // Create an event dispatcher to communicate the captured media back to the parent.
  const dispatch = createEventDispatcher();

  // Reference to the hidden file input element.
  let inputFile: HTMLInputElement;

  /**
   * Handles the file selection event from the hidden file input.
   * When the user captures an image or video, this function dispatches the file to the parent.
   *
   * @param event - The change event from the file input.
   */
  function handleFileChange(event: Event) {
    const target = event.target as HTMLInputElement;
    if (target.files && target.files.length > 0) {
      const file = target.files[0];
      // Log debug information.
      console.debug('[NativeCamera] File captured:', file);
      // Dispatch the 'mediaCaptured' event with the file.
      dispatch('mediaCaptured', { file });
    }
  }

  /**
   * Opens the native camera by programmatically triggering the click on the hidden file input.
   * This function is exported so parent components can use it.
   */
  export function openCamera() {
    if (inputFile) {
      // Reset input to allow the same file to be selected more than once.
      inputFile.value = "";
      // Trigger the file input click event to open the native camera (if supported).
      inputFile.click();
    } else {
      console.error('[NativeCamera] inputFile element is not available.');
    }
  }

  // Log when the component is mounted.
  onMount(() => {
    console.debug('[NativeCamera] Component mounted.');
  });
</script>

<!--
  Hidden file input for capturing media.
  The "capture" attribute (set to "environment") should trigger the rear camera by default on supported devices.
  The "accept" attribute ensures only images and videos are selectable.
-->
<div style={style}>
  <input
    bind:this={inputFile}
    type="file"
    accept="image/*,video/*"
    capture="environment"
    style="display: none;"
    on:change={handleFileChange}
  />
</div>

<style>
  /* Style for the native camera trigger button */
  .native-camera-button {
    padding: 10px 20px;
    background-color: #007bff;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 16px;
    cursor: pointer;
  }

  .native-camera-button:hover {
    background-color: #0056b3;
  }
</style> 