<script lang="ts">
    import { _, waitLocale } from 'svelte-i18n';
    import DesignGuideline from './DesignGuideline.svelte';
    import LargeSeparator from '../components/LargeSeparator.svelte';
    import { replaceOpenMates } from '$lib/actions/replaceText';

    // Export a prop to allow customizing the section title
    export let sectionTitle = $_('design_guidelines.section_title.text');
</script>

{#await waitLocale()}
    <div></div>
{:then}
    <div use:replaceOpenMates>
        <LargeSeparator reverse_direction={true} />
        <section class="centered gradient-section">
            <h3 style="margin-top: 30px">{sectionTitle}</h3>

            <!-- Privacy Design Guideline -->
            <DesignGuideline
                main_icon="icon_lock"
                headline="<mark>{$_('design_guidelines.privacy.headline.text')}</mark>"
                subheadings={[
                    {
                        icon: "icon_anonym",
                        heading: $_('design_guidelines.privacy.anonymization.text'),
                    },
                    {
                        icon: "icon_laptop",
                        heading: $_('design_guidelines.privacy.local_processing.text'),
                    },
                    {
                        icon: "icon_server",
                        heading: $_('design_guidelines.privacy.self_hosting.text'),
                    }
                ]}
                text={$_('design_guidelines.privacy.text.text')}
                subtext={$_('design_guidelines.privacy.subtext.text')}
            />

            <!-- Separator line -->
            <div class="separator"></div>

            <!-- Maximum Good Design Guideline -->
            <DesignGuideline
                main_icon="icon_good"
                headline="<mark>{$_('design_guidelines.maximum_good.headline_1.text')}</mark><br>{$_('design_guidelines.maximum_good.headline_2.text')}"
                subheadings={[
                    {
                        icon: "icon_open_source",
                        heading: $_('design_guidelines.maximum_good.open_source.text'),
                    },
                    {
                        icon: "icon_ai",
                        heading: $_('design_guidelines.maximum_good.provider_independent.text'),
                    },
                    {
                        icon: "icon_chat",
                        heading: $_('design_guidelines.maximum_good.chat_anywhere.text'),
                    }
                ]}
                text={$_('design_guidelines.maximum_good.text.text')}
                subtext={$_('design_guidelines.maximum_good.subtext.text')}
            />
        </section>
        <LargeSeparator />
    </div>
{/await}

<style>
    :root {
        --gradient-height: 100px;
    }

    .centered {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2rem;
        padding: 2rem;
    }

    /* Modified section styling with gradient background */
    .gradient-section {
        position: relative;
        margin-top: calc(-1*var(--gradient-height));
        margin-bottom: calc(-1*var(--gradient-height));
        padding-top: var(--gradient-height);
        padding-bottom: var(--gradient-height);
        background: var(--color-grey-20);
        -webkit-mask-image: linear-gradient(
            to bottom,
            transparent,
            black var(--gradient-height),
            black calc(100% - var(--gradient-height)),
            transparent
        );
        mask-image: linear-gradient(
            to bottom,
            transparent,
            black var(--gradient-height),
            black calc(100% - var(--gradient-height)),
            transparent
        );
    }

    h3 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 600;
        position: relative; /* Ensure text stays above gradients */
        z-index: 1;
    }

    .separator {
        width: 80%;
        border-top: 2px dotted #ccc;
        margin: 1rem 0;
        position: relative; /* Ensure separator stays above gradients */
        z-index: 1;
    }
</style> 