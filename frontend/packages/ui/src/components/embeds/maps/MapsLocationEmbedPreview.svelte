<!--
  frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedPreview.svelte

  Preview component for Maps Location skill embeds.
  Uses UnifiedEmbedPreview as base with skill-specific details content.

  When a user selects a location via the MapsView map picker, the backend
  LocationSkill generates a static map image and stores it in S3. This component
  displays that image (if available) along with the location name.

  Details content:
  - Has map image: shows static map image full-width (hasFullWidthImage=true)
  - No map image: shows location name + coordinates text

  Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  /**
   * Props for maps location embed preview
   */
  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
    /** Unique embed ID */
    id: string;
    /** Display name for the location (e.g. "Current location" or search result name) */
    name?: string;
    /** Human-readable street address from Nominatim reverse geocode or search result */
    address?: string;
    /**
     * Location type from MapsView: "precise_location" or "area".
     * When "area" the user had imprecise/privacy mode on — show a small "Nearby:" prefix label.
     */
    locationType?: string;
    /**
     * Category label for search results (e.g. "Railway", "Airport", "Hotel").
     * Empty string for manual/current-location pins.
     * Shown as a muted line beneath the place name in the text fallback layout.
     */
    placeType?: string;
    /** URL of the static map image stored in S3 */
    mapImageUrl?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }

  let {
    resultContext = 'auto',
    id,
    name: nameProp,
    address: addressProp,
    locationType: locationTypeProp,
    placeType: placeTypeProp,
    mapImageUrl: mapImageUrlProp,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated by embed data events via onEmbedDataUpdated.
  let localName = $state<string>('');
  let localAddress = $state<string>('');
  let localLocationType = $state<string>('area');
  let localPlaceType = $state<string>('');
  let localMapImageUrl = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let storeResolved = $state(false);
  let localTaskId = $state<string | undefined>(undefined);

  // Sync local state from props on initial mount / prop changes
  $effect(() => {
    if (!storeResolved) {
      localName = nameProp ?? '';
      localAddress = addressProp ?? '';
      localLocationType = locationTypeProp ?? 'area';
      localPlaceType = placeTypeProp ?? '';
      localMapImageUrl = mapImageUrlProp;
      localStatus = statusProp ?? 'processing';
      localTaskId = taskIdProp;
    }
  });

  // Expose as derived read-only aliases for clarity
  let name = $derived(localName);
  let address = $derived(localAddress);
  let locationType = $derived(localLocationType);
  let placeType = $derived(localPlaceType);
  let mapImageUrl = $derived(localMapImageUrl);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);

  /**
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the server sends updated embed content (e.g. status change).
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[MapsLocationEmbedPreview] Received embed data update for ${id}`);

    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
      if (data.status !== 'processing') { storeResolved = true; }
    }

    const content = data.decodedContent;
    if (content) {
      if (content.name !== undefined) localName = (content.name as string) || '';
      if (content.address !== undefined) localAddress = (content.address as string) || '';
      if (content.location_type !== undefined) localLocationType = (content.location_type as string) || 'area';
      if (content.place_type !== undefined) localPlaceType = (content.place_type as string) || '';
      if (content.map_image_url) {
        localMapImageUrl = content.map_image_url as string;
      }
    }
  }

  // Skill name from translations
  let skillName = $derived($text('common.location'));

  // skillIconName is still passed to the BasicInfosBar (always pin for location skill)
  const skillIconName = 'pin';

  // Whether we have a map image to display full-width
  let hasImage = $derived(!!mapImageUrl && status !== 'error');

  // Show "Nearby:" label only in area/imprecise mode — the pin was randomised so the
  // address is approximate and we want to signal that to the user.
  let showNearbyLabel = $derived(locationType === 'area');

  // Primary display name (e.g. "Berlin Hauptbahnhof").
  // `name` may be a two-line string from legacy locationIndicatorText — take only the first line.
  let primaryName = $derived(name ? name.split('\n')[0].trim() : '');


</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
  {id}
  appId="maps"
  skillId="location"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  hasFullWidthImage={hasImage}
  showStatus={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <ResultEmbedCard title={primaryName || $text('common.location')} description={address} imageUrl={hasImage ? proxyImage(mapImageUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : undefined} imageAlt={name || $text('common.location')} sourceLabel={placeType || undefined}>
      {#snippet facts()}
        {#if showNearbyLabel}<span data-testid="maps-location-approximate">{$text('embeds.maps_location.nearby')} · Approximate area</span>{/if}
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>
