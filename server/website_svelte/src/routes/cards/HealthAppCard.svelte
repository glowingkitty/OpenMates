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

  // Calculate the start time based on the earliest appointment
  $: startTime = appointments.length > 0 
    ? Math.min(...appointments.map(a => a.start)) 
    : 9; // Default to 9 if no appointments

  // Generate 5 time slots starting from the calculated start time
  $: timeSlots = Array.from({length: 5}, (_, i) => `${startTime + i}:00`);

  // Convert absolute times to relative positions (0-4)
  $: relativeAppointments = appointments.map(app => ({
    ...app,
    start: app.start - startTime,
    end: app.end - startTime
  }));
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
          {#each timeSlots as slot}
            <div class="app-card-text">{slot}</div>
          {/each}

          {#each relativeAppointments as appointment}
            <div class="appointment-indicator {appointment.type}"
                 style="--start-hour: {appointment.start}; --end-hour: {appointment.end};">
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </svelte:fragment>
</BaseAppCard> 