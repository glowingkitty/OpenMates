<script lang="ts">
    import {
        externalLinks,
        privacyPolicyLinks,
        MetaTags,
        getMetaTags
    } from '@openmates/shared';
    import { _, locale } from 'svelte-i18n';

    const meta = getMetaTags('legalPrivacy');

    // Get current build date and format it using the active locale, fallback to 'en' if undefined
    $: buildDate = new Date().toLocaleDateString($locale || 'en', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });

    // Function to sanitize HTML, allowing only <mark> and <br> tags
    function sanitizeHtml(html: string) {
        // Remove all HTML tags except <mark> and <br>
        return html
            .replace(/<(?!\/?(mark|br)(?=>|\s.*>))\/?(?:.|\n)*?>/gm, '')
            // Ensure proper closing of mark tags
            .replace(/<mark>/g, '<mark>')
            .replace(/<\/mark>/g, '</mark>')
            // Ensure self-closing br tags
            .replace(/<br>/g, '<br />');
    }
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>{@html sanitizeHtml($_('legal.privacy.title.text'))}</h1>

    <p class="last-updated">{@html sanitizeHtml(`${$_('legal.privacy.last_updated.text')}: ${buildDate}`)}</p>

    <section>
        <h2>{@html sanitizeHtml($_('legal.privacy.data_protection.heading.text'))}</h2>
        <p>{@html sanitizeHtml($_('legal.privacy.data_protection.overview.text'))}</p>
        <p>{@html sanitizeHtml($_('legal.privacy.data_protection.current_state.text'))}</p>
    </section>

    <section>
        <h2>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.heading.text'))}</h2>
        <p>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.description.text'))}</p>
        <ul>
            <li>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.data_points.ip.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.data_points.browser.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.data_points.logs.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.data_points.performance.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.vercel_hosting.data_points.server_logs.text'))}</li>
        </ul>
        <p>
            {@html sanitizeHtml($_('legal.privacy.vercel_hosting.more_info.text'))}
            <a href={privacyPolicyLinks.vercel} target="_blank" rel="noopener noreferrer">
                {@html sanitizeHtml($_('legal.privacy.vercel_hosting.privacy_policy_link.text'))}
            </a>.
        </p>
    </section>

    <section>
        <h2>{@html sanitizeHtml($_('legal.privacy.discord_integration.heading.text'))}</h2>
        <p>{@html sanitizeHtml($_('legal.privacy.discord_integration.description.text'))}</p>
        <ul>
            <li>{@html sanitizeHtml($_('legal.privacy.discord_integration.data_points.account.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.discord_integration.data_points.usage.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.discord_integration.data_points.communication.text'))}</li>
            <li>{@html sanitizeHtml($_('legal.privacy.discord_integration.data_points.other.text'))}</li>
        </ul>
        <p>
            {@html sanitizeHtml($_('legal.privacy.discord_integration.admin_access.text'))}
            <a href={privacyPolicyLinks.discord} target="_blank" rel="noopener noreferrer">
                {@html sanitizeHtml($_('legal.privacy.discord_integration.privacy_policy_link.text'))}
            </a>.
        </p>
    </section>

    <section>
        <h2>{@html sanitizeHtml($_('legal.privacy.contact.heading.text'))}</h2>
        <p>{@html sanitizeHtml($_('legal.privacy.contact.questions.text'))}</p>
        <p>{@html sanitizeHtml($_('legal.privacy.contact.email.text'))}: <a href="{externalLinks.email}">{externalLinks.email.replace('mailto:', '')}</a></p>
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