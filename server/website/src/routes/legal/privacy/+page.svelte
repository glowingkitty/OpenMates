<script lang="ts">
    import { externalLinks } from '$lib/config/links';
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('legalPrivacy');
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>Privacy Policy</h1>
    
    <section>
        <h2>1. Data Protection Overview</h2>
        <p>This privacy policy explains how we collect, use, and protect your personal data when you use our website.</p>
    </section>

    <section>
        <h2>2. Contact Information</h2>
        <p>For questions about data protection:</p>
        <p>Email: <a href="mailto:{externalLinks.email}">{externalLinks.email}</a></p>
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