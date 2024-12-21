<script lang="ts">
    import { externalLinks } from '$lib/config/links';
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('legalImprint');
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>Legal Notice (Imprint)</h1>
    
    <section>
        <h2>Company Information</h2>
        <p>OpenMates</p>
        <p>[Company Address]</p>
        <p>Email: <a href={externalLinks.email}>contact@openmates.com</a></p>
    </section>

    <section>
        <h2>Represented by</h2>
        <p>[Legal Representative Name]</p>
    </section>

    <section>
        <h2>Contact</h2>
        <p>Phone: [Phone Number]</p>
        <p>Email: <a href={externalLinks.email}>contact@openmates.com</a></p>
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