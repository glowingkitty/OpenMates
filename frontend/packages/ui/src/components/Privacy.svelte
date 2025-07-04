<script lang="ts">
    import { text } from '@repo/ui';
    import { locale } from 'svelte-i18n';
    import { externalLinks, privacyPolicyLinks } from '../config/links';

    // Get current build date and format it using the active locale, fallback to 'en' if undefined
    $: buildDate = new Date().toLocaleDateString($locale || 'en', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
</script>

<div class="legal-container">
    <h1>{@html $text('legal.privacy.title.text')}</h1>

    <p class="last-updated">{@html $text('legal.privacy.last_updated.text')}: {buildDate}</p>

    <section>
        <h2>{@html $text('legal.privacy.data_protection.heading.text')}</h2>
        <p>{@html $text('legal.privacy.data_protection.overview.text')}</p>
        <p>{@html $text('legal.privacy.data_protection.website_vs_webapp.text')}</p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.vercel.heading.text')}</h2>
        <p>{@html $text('legal.privacy.vercel.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.vercel} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.vercel.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.webapp_services.heading.text')}</h2>
        <p>{@html $text('legal.privacy.webapp_services.intro.text')}</p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.hetzner.heading.text')}</h2>
        <p>{@html $text('legal.privacy.hetzner.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.hetzner} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.hetzner.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.ip_api.heading.text')}</h2>
        <p>{@html $text('legal.privacy.ip_api.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.ipApi} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.ip_api.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.mailjet.heading.text')}</h2>
        <p>{@html $text('legal.privacy.mailjet.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.mailjet} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.mailjet.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.sightengine.heading.text')}</h2>
        <p>{@html $text('legal.privacy.sightengine.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.sightengine} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.sightengine.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.stripe.heading.text')}</h2>
        <p>{@html $text('legal.privacy.stripe.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.stripe} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.stripe.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.mistral.heading.text')}</h2>
        <p>{@html $text('legal.privacy.mistral.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.mistral} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.mistral.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.aws.heading.text')}</h2>
        <p>{@html $text('legal.privacy.aws.description.text')}</p>
        <p>
            <a href={privacyPolicyLinks.aws} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.aws.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.security_measures.heading.text')}</h2>
        <p>{@html $text('legal.privacy.security_measures.intro.text')}</p>
        
        <h2>{@html $text('legal.privacy.security_measures.device_fingerprinting.subheading.text')}</h2>
        <p>{@html $text('legal.privacy.security_measures.device_fingerprinting.purpose.text')}</p>
        <p>{@html $text('legal.privacy.security_measures.device_fingerprinting.storage.text')}</p>
        <p>{@html $text('legal.privacy.security_measures.device_fingerprinting.ip_logging.text')}</p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.discord_integration.heading.text')}</h2>
        <p>{@html $text('legal.privacy.discord_integration.description.text')}</p>
        <p>{@html $text('legal.privacy.discord_integration.admin_access.text')}</p>
        <p>
            <a href={privacyPolicyLinks.discord} target="_blank" rel="noopener noreferrer">
                {@html $text('legal.privacy.discord_integration.privacy_policy_link.text')}
            </a>
        </p>
    </section>

    <section>
        <h2>{@html $text('legal.privacy.contact.heading.text')}</h2>
        <p>{@html $text('legal.privacy.contact.questions.text')}</p>
        <p>{@html $text('legal.privacy.contact.email.text')}: <a href="{externalLinks.email}">{externalLinks.email.replace('mailto:', '')}</a></p>
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
