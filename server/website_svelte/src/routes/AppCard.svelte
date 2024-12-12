<script lang="ts">
  export let size: 'small' | 'large' = 'small';
  export let type: string = 'health'; // e.g., 'health', 'events', etc.
  export let showCalendar: boolean = false;
</script>

<div class="app-card {size} {type}">
  <div>
    <slot name="header" />
    <slot name="content" />
    <slot name="footer" />
  </div>

  {#if showCalendar}
    <div class="app-card-secondary-app calendar">
      <div class="time-slots">
        <div class="app-card-text">9:00</div>
        <div class="app-card-text">10:00</div>
        <div class="app-card-text">11:00</div>
        <div class="app-card-text">12:00</div>
        <div class="app-card-text">13:00</div>

        <slot name="appointments" />
      </div>
    </div>
  {/if}
</div>
