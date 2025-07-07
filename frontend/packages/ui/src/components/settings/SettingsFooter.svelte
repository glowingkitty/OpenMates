<script lang="ts">
    import { text } from '@repo/ui';
    import { externalLinks, getWebsiteUrl } from '../../config/links';
</script>

<div class="submenu-section">
    <!-- TODO Show again once docs are implemented -->
    <!-- <div class="submenu-group">
        <h3>{@html $text('settings.docs.text')}</h3>
        <a 
            href={getWebsiteUrl('/docs/user-guide')} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.user_guide.text')}</a>
        <a 
            href={getWebsiteUrl('/docs/api-docs')} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.api_docs.text')}</a>
    </div> -->

    <div class="submenu-group">
        <h3>{@html $text('settings.contact.text')}</h3>
        <a 
            href={externalLinks.discord} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.discord.text')}</a>
        <a 
            href={externalLinks.email} 
            class="submenu-link"
        >{@html $text('settings.email.text')}</a>
    </div>

    <div class="submenu-group">
        <h3>{@html $text('settings.legal.text')}</h3>
        <a 
            href={getWebsiteUrl(externalLinks.legal.imprint)} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.imprint.text')}</a>
        <a 
            href={getWebsiteUrl(externalLinks.legal.privacyPolicy)} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.privacy.text')}</a>
        <a 
            href={getWebsiteUrl(externalLinks.legal.terms)} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.terms_and_conditions.text')}</a>
    </div>

    <div class="submenu-group">
        <h3>Web app version</h3>
        <span class="version-text">v2025-06-30-15-54-f9a9js</span>
    </div>
</div>

<style>
    .submenu-section {
        padding: 0 16px 16px;
    }

    .submenu-group {
        margin-bottom: 16px;
    }

    .submenu-group h3 {
        color: var(--color-grey-60);
        font-size: 14px;
        font-weight: 600;
        margin: 6px 0;
    }

    .submenu-link {
        display: block;
        color: var(--color-grey-50);
        text-decoration: none;
        padding: 6px 0;
        font-size: 14px;
        transition: color 0.2s ease;
    }

    .submenu-link:hover {
        color: var(--color-primary);
    }

    .version-text {
        color: var(--color-grey-50);
        font-size: 14px;
        padding: 6px 0;
        display: block;
    }
</style>
