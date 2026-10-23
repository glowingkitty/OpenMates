<!-- Shared calendar presentation; no app-specific state belongs here. -->
<script lang="ts">
  import type { ComponentProps } from 'svelte';
  import CalendarDatePresentation from '@repo/public-site/components/results/EmbedCalendarDate.svelte';
  let { date, timezone, locale, timeLabel, size }: ComponentProps<typeof CalendarDatePresentation> = $props();
</script>

<CalendarDatePresentation {date} {timezone} {locale} {timeLabel} {size} />
