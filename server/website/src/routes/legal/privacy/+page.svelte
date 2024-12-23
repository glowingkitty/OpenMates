<script lang="ts">
    import { externalLinks } from '$lib/config/links';
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('legalPrivacy');

    // Get current build date and format it
    const buildDate = new Date().toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>Privacy Policy</h1>

    <p class="last-updated">Last Updated: {buildDate}</p>

    <section>
        <h2>1. Data Protection Overview</h2>
        <p>This privacy policy explains what happens to your data when you use our website. We are committed to transparency regarding data handling.</p>
        <p>We currently do not collect, store, or process any personal data directly through this website. The website is hosted via GitHub Pages, and your interaction with this site is subject to GitHub's privacy practices.</p>
    </section>

    <section>
        <h2>2. GitHub Pages Hosting</h2>
        <p>This website is hosted using GitHub Pages. When you visit this website, your request is processed by GitHub's servers. GitHub may collect technical information including:</p>
        <ul>
            <li>IP addresses</li>
            <li>Browser type and version</li>
            <li>Basic access logs</li>
        </ul>
        <p>For more information about GitHub's data practices, please refer to the <a href="https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub Privacy Statement</a>.</p>
    </section>

    <section>
        <h2>3. Discord Integration</h2>
        <p>If you choose to join our Discord community through links provided on this website, please note that Discord will collect and process your data according to their privacy policy. This includes:</p>
        <ul>
            <li>Account information</li>
            <li>Usage data</li>
            <li>Communication content</li>
            <li>Other information as outlined in Discord's privacy policy</li>
        </ul>
        <p>As Discord server administrators, we have access to all public communications, member lists, and other information shared within our Discord community. However, this information is hosted and primarily processed by Discord. We do not extract, store, or process this data outside of Discord's platform. For more information about how Discord handles your data, please review <a href="https://discord.com/privacy" target="_blank" rel="noopener noreferrer">Discord's Privacy Policy</a>.</p>
    </section>

    <section>
        <h2>4. Contact Information</h2>
        <p>For questions about data protection:</p>
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

    .last-updated {
        font-style: italic;
        color: #666;
        margin-bottom: 2rem;
    }
</style> 