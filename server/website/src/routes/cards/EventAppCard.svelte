<script lang="ts">
  import BaseAppCard from './BaseAppCard.svelte';
  
  export let size: 'small' | 'large' = 'small';
  export let date: string;
  export let time: string;
  export let eventName: string;
  export let participants: number;
  export let imageUrl: string;
</script>

<BaseAppCard {size} type="events" title={eventName}>
  <svelte:fragment slot="top">
    <div class="app-card-subheader-top">
      <div class="event-header">
        <div class="event-image" style="background-image: url('{imageUrl}');"></div>
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