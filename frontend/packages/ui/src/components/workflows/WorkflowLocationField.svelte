<script lang="ts">
  import { text } from '../../i18n/translations';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import MapsView from '../enter_message/MapsView.svelte';

  type LocationSelection = {
    text: string;
    city: string;
    latitude: number;
    longitude: number;
  };

  let {
    value = '',
    latitude,
    longitude,
    mode,
    required = false,
    onChange
  }: {
    value?: string;
    latitude?: number;
    longitude?: number;
    mode: 'weather' | 'events' | 'home';
    required?: boolean;
    onChange: (selection: LocationSelection) => void;
  } = $props();

  let open = $state(false);
  const Pin = getLucideIcon('map-pin');
  const tr = (key: string) => $text(`workflows.builder.${key}`);

  function selectLocation(event: CustomEvent<{ attrs?: Record<string, unknown> }>): void {
    const attrs = event.detail?.attrs ?? {};
    const latitude = Number(attrs.preciseLat ?? attrs.lat);
    const longitude = Number(attrs.preciseLon ?? attrs.lon);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    const city = String(attrs.city ?? '').trim();
    const name = String(attrs.name ?? '').trim();
    const address = String(attrs.address ?? '').trim();
    if (mode === 'home' && !city) return;
    onChange({
      text: mode === 'home' ? city : name || city || address,
      city,
      latitude,
      longitude
    });
    open = false;
  }
</script>

<div class="location-field" data-testid="workflow-location-field">
  <span class="label">{tr('location')}{required ? ' *' : ''}</span>
  <button
    type="button"
    class="location-button"
    data-testid="workflow-node-location-picker"
    aria-expanded={open}
    onclick={() => open = !open}
  >
    <Pin size={16} aria-hidden="true" />
    <span>{value || tr('choose_location')}</span>
  </button>
  {#if mode === 'home'}<span class="help">{tr('home_location_scope')}</span>{/if}
  {#if open}
    <div class="map-shell" data-testid="workflow-location-map">
      <MapsView
        defaultImprecise={false}
        allowImprecise={false}
        allowCurrentLocation={false}
        allowFullscreen={false}
        requireCity={mode === 'home'}
        initialLatitude={latitude}
        initialLongitude={longitude}
        initialLocationText={value}
        on:locationselected={selectLocation}
        on:close={() => open = false}
        on:toggleFullscreen={() => undefined}
      />
    </div>
  {/if}
</div>

<style>
  .location-field { grid-column:1/-1; display:grid; gap:var(--spacing-4); min-width:0; text-align:start; }
  .label { font-size:max(16px, 1rem); font-weight:650; }
  .location-button { box-sizing:border-box; width:100%; min-height:3.375rem; display:flex; align-items:center; gap:var(--spacing-6); padding:.8rem 1.1rem; border:0; border-radius:var(--radius-8); background:var(--workflow-input-surface, var(--color-grey-10)); color:var(--color-font-primary); box-shadow:var(--shadow-sm); font:inherit; font-size:max(16px, 1rem); text-align:start; cursor:pointer; }
  .location-button span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .help { color:var(--color-font-secondary); font-size:max(14px, .875rem); }
  .map-shell { position:relative; box-sizing:border-box; width:100%; min-width:0; min-height:28rem; overflow:hidden; border-radius:var(--radius-6); background:var(--color-grey-0); box-shadow:var(--shadow-sm); }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:730px) { .map-shell { min-height:24rem; } }
</style>
