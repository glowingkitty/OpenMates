<script lang="ts">
  import BaseAppCard from './BaseAppCard.svelte';
  
  export let size: 'small' | 'large' = 'small';
  export let date: string;
  export let start: string;
  export let end: string;
  export let doctorName: string;
  export let specialty: string;
  export let rating: number;
  export let ratingCount: number;
  export let showCalendar: boolean = false;
  export let existingAppointments: Array<{start: string, end: string}> = [];

  // Helper function to convert time string (HH:MM) to decimal hours
  function timeToDecimal(timeStr: string): number {
    const [hours, minutes] = timeStr.split(':').map(Number);
    return hours + (minutes / 60);
  }

  // Convert appointment times to decimal hours for positioning
  $: allAppointments = [
    { start: timeToDecimal(start), end: timeToDecimal(end), type: 'dashed' as const },
    ...existingAppointments.map(apt => ({
      start: timeToDecimal(apt.start),
      end: timeToDecimal(apt.end),
      type: 'solid' as const
    }))
  ];

  // Calculate the start time based on the earliest appointment
  $: calendarStartTime = Math.floor(
    Math.min(...allAppointments.map(a => a.start))
  );

  // Generate 5 time slots starting from the calculated start time
  $: timeSlots = Array.from({length: 5}, (_, i) => `${calendarStartTime + i}:00`);

  // Convert absolute times to relative positions (0-4)
  $: relativeAppointments = allAppointments.map(app => ({
    ...app,
    start: app.start - calendarStartTime,
    end: app.end - calendarStartTime
  }));

  // Combine start and end time for display
  $: timeDisplay = `${start} - ${end}`;
</script>

<BaseAppCard {size} type="health" title={doctorName} subtitle={specialty}>
  <svelte:fragment slot="top">
    <div class="app-card-subheader-top">
      <div class="app-card-h3">{date}</div>
      <div class="app-card-h2">{timeDisplay}</div>
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