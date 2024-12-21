<script lang="ts">
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('legalTerms');
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>Terms and Conditions</h1>
    
    <section>
        <h2>1. Agreement to Terms</h2>
        <p>By accessing and using this website, you accept and agree to be bound by the terms and conditions outlined here.</p>
    </section>

    <section>
        <h2>2. Use License</h2>
        <p>Permission is granted to temporarily access the materials on our website for personal, non-commercial use only.</p>
    </section>

    <!-- Add more sections as needed -->
</div>

<style>
    .legal-container {
        max-width: 800px;
        margin: 2rem auto;
        padding: 0 1rem;
    }

    section {
        margin: 2rem 0;
    }

    h1 {
        font-size: 2rem;
        margin-bottom: 2rem;
    }

    h2 {
        font-size: 1.5rem;
        margin: 1.5rem 0 1rem;
    }
</style> 