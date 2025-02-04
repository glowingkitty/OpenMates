<script lang="ts">
    import {
        // Components
        MetaTags,
        // Config
        getMetaTags,
        externalLinks
    } from '@openmates/shared';
    import { _ } from 'svelte-i18n';

    const meta = getMetaTags('legalTerms');

    // Get current build date and format it
    const buildDate = new Date().toLocaleDateString('de-DE', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>{$_('legal.terms.title.text')}</h1>
    
    <p class="last-updated">{$_('legal.terms.last_updated.text')}: {buildDate}</p>

    <section>
        <h2>1. {$_('legal.terms.agreement.heading.text')}</h2>
        <p>{$_('legal.terms.agreement.description.text')}</p>
    </section>

    <section>
        <h2>2. {$_('legal.terms.about.heading.text')}</h2>
        <p>{$_('legal.terms.about.description.text')}</p>
    </section>

    <section>
        <h2>3. {$_('legal.terms.intellectual_property.heading.text')}</h2>
        <p>{$_('legal.terms.intellectual_property.description.text')}</p>
    </section>

    <section>
        <h2>4. {$_('legal.terms.use_license.heading.text')}</h2>
        <p>{$_('legal.terms.use_license.description.text')}</p>
        <ul>
            <li>{$_('legal.terms.use_license.restrictions.modify.text')}</li>
            <li>{$_('legal.terms.use_license.restrictions.commercial.text')}</li>
            <li>{$_('legal.terms.use_license.restrictions.reverse_engineer.text')}</li>
            <li>{$_('legal.terms.use_license.restrictions.copyright.text')}</li>
        </ul>
    </section>

    <section>
        <h2>5. {$_('legal.terms.discord.heading.text')}</h2>
        <p>{$_('legal.terms.discord.description.text')}</p>
        <ul>
            <li>{$_('legal.terms.discord.rules.tos.text')}</li>
            <li>{$_('legal.terms.discord.rules.age.text')}</li>
            <li>{$_('legal.terms.discord.rules.respect.text')}</li>
            <li>{$_('legal.terms.discord.rules.content.text')}</li>
        </ul>
    </section>

    <section>
        <h2>6. {$_('legal.terms.disclaimer.heading.text')}</h2>
        <p>{$_('legal.terms.disclaimer.description.text')}</p>
    </section>

    <section>
        <h2>7. {$_('legal.terms.limitations.heading.text')}</h2>
        <p>{$_('legal.terms.limitations.description.text')}</p>
        <ul>
            <li>{$_('legal.terms.limitations.list.website_use.text')}</li>
            <li>{$_('legal.terms.limitations.list.information.text')}</li>
            <li>{$_('legal.terms.limitations.list.technical.text')}</li>
        </ul>
    </section>

    <section>
        <h2>8. {$_('legal.terms.governing_law.heading.text')}</h2>
        <p>{$_('legal.terms.governing_law.explanation.text')}</p>
    </section>

    <section>
        <h2>9. {$_('legal.terms.contact.heading.text')}</h2>
        <p>{$_('legal.terms.contact.intro.text')}</p>
        <p>{$_('legal.terms.contact.email_label.text')}: <a href="{externalLinks.email}">{externalLinks.email.replace('mailto:', '')}</a></p>
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