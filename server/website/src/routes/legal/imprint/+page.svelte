<script lang="ts">
    import { externalLinks } from '$lib/config/links';
    import MetaTags from '../../components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('legalImprint');
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>Legal Notice (Imprint)</h1>

    <section>
        <h2>Information according to § 5 TMG</h2>
        <p><span class="contact-info info-1"></span></p>
        <p><span class="contact-info info-2"></span></p>
        <p><span class="contact-info info-3"></span></p>
        <p><span class="contact-info info-4"></span></p>
    </section>

    <section>
        <h2>Contact</h2>
        <p>Email: <a href="mailto:{externalLinks.email}">{externalLinks.email}</a></p>
    </section>
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

    p {
        margin: 0.5rem 0;
    }

    .contact-info {
        display: inline-block;
        height: 1.2em;
        background-repeat: no-repeat;
        background-position: left center;
        background-size: contain;
        user-select: none;
    }

    .info-1 {
        width: 100%;
        height: 20px;
        background-image: url('/images/legal/1.svg');
    }

    .info-2 {
        width: 100%;
        height: 20px;
        background-image: url('/images/legal/2.svg');
    }

    .info-3 {
        width: 100%;
        height: 20px;
        background-image: url('/images/legal/3.svg');
    }

    .info-4 {
        width: 100%;
        height: 20px;
        background-image: url('/images/legal/4.svg');
    }
</style> 