<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';

  // Create event dispatcher to notify the parent component when media is captured.
  const dispatch = createEventDispatcher();

  // Reference to the hidden file input element.
  let inputFile: HTMLInputElement;

  /**
   * Triggered when a file is selected via the native camera.
   * We then dispatch this file (which can be an image or video) up to the parent.
   *
   * @param event The change event from the file input.
   */
  function handleFileChange(event: Event) {
    const target = event.target as HTMLInputElement;
    if (target.files && target.files.length > 0) {
      const file = target.files[0];
      // Log the file details.
      console.debug('[NativeCamera] File captured:', file);
      // Dispatch event with the captured file for further processing (e.g. uploading)
      dispatch('mediaCaptured', { file });
    }
  }

  /**
   * Opens the native camera by triggering a click on the hidden file input.
   */
  function openCamera() {
    if (inputFile) {
      // Reset input to allow selecting the same file more than once.
      inputFile.value = "";
      // Trigger the file input click to open the native camera control.
      inputFile.click();
    } else {
      console.error('[NativeCamera] inputFile element is not available.');
    }
  }

  // Optional: Any onMount initialization if needed.
  onMount(() => {
    console.debug('[NativeCamera] Component mounted.');
  });
</script>

<!-- Hidden file input that leverages the native camera control when clicked.
     The 'capture' attribute causes the device to use the rear camera.
     Accept attribute limits file types to images and videos. -->
<input
  bind:this={inputFile}
  type="file"
  accept="image/*,video/*"
  capture="environment"
  style="display: none;"
  on:change={handleFileChange}
/>

<!-- Button which the user taps to launch the native camera -->
<button class="native-camera-button" on:click={openCamera} aria-label="Open native camera">
  Open Camera
</button>

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