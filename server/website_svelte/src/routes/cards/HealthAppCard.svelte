<script lang="ts">
  import BaseAppCard from './BaseAppCard.svelte';
  
  export let size: 'small' | 'large' = 'small';
  export let date: string;
  export let time: string;
  export let doctorName: string;
  export let specialty: string;
  export let rating: number;
  export let ratingCount: number;
  export let showCalendar: boolean = false;
  export let appointments: Array<{start: number, end: number, type: 'dashed' | 'solid'}> = [];
</script>

<BaseAppCard {size} type="health" title={doctorName} subtitle={specialty}>
  <svelte:fragment slot="top">
    <div class="app-card-subheader-top">
      <div class="app-card-h3">{date}</div>
      <div class="app-card-h2">{time}</div>
    </div>
  </svelte:fragment>

  <svelte:fragment slot="bottom">
    <div class="app-card-subheader-bottom">
      <span class="app-card-h3">★</span>
      <span class="app-card-h3">{rating}</span>
      <span class="app-card-h3">({ratingCount} <span class="ratings-text">ratings</span>)</span>
    </div>
  </svelte:fragment>

  <svelte:fragment slot="secondary">
    {#if showCalendar}
      <div class="app-card-secondary-app calendar">
        <div class="time-slots">
          <div class="app-card-text">9:00</div>
          <div class="app-card-text">10:00</div>
          <div class="app-card-text">11:00</div>
          <div class="app-card-text">12:00</div>
          <div class="app-card-text">13:00</div>

          {#each appointments as appointment}
            <div class="appointment-indicator {appointment.type}"
                 style="--start-hour: {appointment.start}; --end-hour: {appointment.end};">
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </svelte:fragment>
</BaseAppCard> 