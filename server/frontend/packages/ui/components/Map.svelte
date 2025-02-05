<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';

    
    let mapElement: HTMLDivElement;
    let L: typeof import('leaflet');

    onMount(async () => {
        if (!browser) return;

        // Dynamically import Leaflet only on the client side
        const leaflet = await import('leaflet');
        L = leaflet.default;

        // Import Leaflet CSS
        await import('leaflet/dist/leaflet.css');

        // Initialize the map
        const map = L.map(mapElement).setView([51.505, -0.09], 13);

        // Add the OpenStreetMap tiles
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

        // Add a marker
        L.marker([51.5, -0.09])
            .addTo(map)
            .bindPopup('A sample marker!')
            .openPopup();

        // Cleanup on component destruction
        return () => {
            map.remove();
        };
    });
</script>

<div bind:this={mapElement} class="map" />

<style>
    .map {
        height: 400px;
        width: 100%;
        z-index: 1;
    }

    /* Fix Leaflet marker icons */
    :global(.leaflet-default-icon-path) {
        background-image: url('https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png');
    }
    :global(.leaflet-default-shadow-path) {
        background-image: url('https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png');
    }
</style>
