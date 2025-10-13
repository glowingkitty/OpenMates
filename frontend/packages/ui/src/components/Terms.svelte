<script lang="ts">
    import { text } from '@repo/ui';
    import { locale } from 'svelte-i18n';
    import { externalLinks } from '../config/links';

    // Get current build date and format it using the active locale, fallback to 'en' if undefined using Svelte 5 runes
    let buildDate = $derived(new Date().toLocaleDateString($locale || 'en', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    }));
</script>

<section class="legal-container">
    <h1>{@html $text('legal.terms.title.text')}</h1>

    <p class="last-updated">{@html $text('legal.terms.last_updated.text')}: {buildDate}</p>

    <section>
        <h2>1. {@html $text('legal.terms.agreement.heading.text')}</h2>
        <p>{@html $text('legal.terms.agreement.description.text')}</p>
    </section>

    <section>
        <h2>2. {@html $text('legal.terms.about.heading.text')}</h2>
        <p>{@html $text('legal.terms.about.description.text')}</p>
    </section>

    <section>
        <h2>3. {@html $text('legal.terms.intellectual_property.heading.text')}</h2>
        <p>{@html $text('legal.terms.intellectual_property.description.text')}</p>
    </section>

    <section>
        <h2>4. {@html $text('legal.terms.use_license.heading.text')}</h2>
        <p>{@html $text('legal.terms.use_license.description.text')}</p>
        <ul>
            <li>{@html $text('legal.terms.use_license.restrictions.modify.text')}</li>
            <li>{@html $text('legal.terms.use_license.restrictions.commercial.text')}</li>
            <li>{@html $text('legal.terms.use_license.restrictions.reverse_engineer.text')}</li>
            <li>{@html $text('legal.terms.use_license.restrictions.copyright.text')}</li>
        </ul>
    </section>

    <section>
        <h2>5. {@html $text('legal.terms.discord.heading.text')}</h2>
        <p>{@html $text('legal.terms.discord.description.text')}</p>
        <ul>
            <li>{@html $text('legal.terms.discord.rules.tos.text')}</li>
            <li>{@html $text('legal.terms.discord.rules.age.text')}</li>
            <li>{@html $text('legal.terms.discord.rules.respect.text')}</li>
            <li>{@html $text('legal.terms.discord.rules.content.text')}</li>
        </ul>
    </section>

    <section>
        <h2>6. {@html $text('legal.terms.disclaimer.heading.text')}</h2>
        <p>{@html $text('legal.terms.disclaimer.description.text')}</p>
    </section>

    <section>
        <h2>7. {@html $text('legal.terms.limitations.heading.text')}</h2>
        <p>{@html $text('legal.terms.limitations.description.text')}</p>
        <ul>
            <li>{@html $text('legal.terms.limitations.list.website_use.text')}</li>
            <li>{@html $text('legal.terms.limitations.list.information.text')}</li>
            <li>{@html $text('legal.terms.limitations.list.technical.text')}</li>
        </ul>
    </section>

    <section>
        <h2>8. {@html $text('legal.terms.governing_law.heading.text')}</h2>
        <p>{@html $text('legal.terms.governing_law.explanation.text')}</p>
    </section>

    <section>
        <h2>9. {@html $text('legal.terms.contact.heading.text')}</h2>
        <p>{@html $text('legal.terms.contact.intro.text')}</p>
        <p>{@html $text('legal.terms.contact.email_label.text')}: <a href="{externalLinks.email}">{externalLinks.email.replace('mailto:', '')}</a></p>
    </section>
</section>

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