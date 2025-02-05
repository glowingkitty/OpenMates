<script lang="ts">
  import BaseAppCard from './BaseAppCard.svelte';
  
  export let size: 'small' | 'large' = 'small';
  export let date: string;
  export let time: string;
  export let eventName: string;
  export let participants: number;
  export let imageUrl: string;

  // Extract the filename from the URL to use as a CSS class
  $: imageClass = imageUrl.split('/').pop()?.replace(/[^a-zA-Z0-9]/g, '-') || '';
</script>

<BaseAppCard {size} type="events" title={eventName}>
  <svelte:fragment slot="top">
    <div class="app-card-subheader-top">
      <div class="event-header">
        <div class="event-image {imageClass}"></div>
        <div class="event-time">
          <div class="app-card-h3">{date}</div>
          <div class="app-card-h2">{time}</div>
        </div>
      </div>
    </div>
  </svelte:fragment>

  <svelte:fragment slot="bottom">
    <div class="app-card-subheader-bottom">
      <span class="app-card-h3">{participants}</span>
      <span class="app-card-h3 participants-text">participants</span>
    </div>
  </svelte:fragment>
</BaseAppCard>

<style>
  /* Define a class for each possible image */
  .group1-jpg {
    background-image: url('@openmates/ui/static/images/examples/group1.jpg');
  }
  .group2-jpg {
    background-image: url('@openmates/ui/static/images/examples/group2.jpg');
  }
  /* Add more image classes as needed */
</style> 