<script lang="ts">
    import { _, waitLocale } from 'svelte-i18n';
    import DesignGuideline from './DesignGuideline.svelte';
    import LargeSeparator from '../components/LargeSeparator.svelte';
    import { onMount, tick } from 'svelte';

    // Props using Svelte 5 runes
    let { sectionTitle = undefined }: { sectionTitle?: string | undefined } = $props();
    
    // Make section title reactive to locale changes using Svelte 5 runes
    let actualTitle = $derived(sectionTitle || $_('design_guidelines.section_title'));

    onMount(() => {
        // No need to initialize content as translations are pre-processed
    });
</script>

{#await waitLocale()}
    <div></div>
{:then}
    <div>
        <LargeSeparator reverse_direction={true} />
        <section class="centered gradient-section">
            <h3 style="margin-top: 30px">{@html actualTitle}</h3>

            <!-- Privacy Design Guideline -->
            <DesignGuideline
                main_icon="icon_lock"
                headline={$_('design_guidelines.privacy.headline')}
                subheadings={[
                    {
                        icon: "icon_anonym",
                        heading: $_('design_guidelines.privacy.anonymization'),
                    },
                    {
                        icon: "icon_laptop",
                        heading: $_('design_guidelines.privacy.local_processing'),
                    },
                    {
                        icon: "icon_server",
                        heading: $_('design_guidelines.privacy.self_hosting'),
                    }
                ]}
                text={$_('design_guidelines.privacy.text')}
                subtext={$_('design_guidelines.privacy.subtext')}
            />

            <!-- Separator line -->
            <div class="separator"></div>

            <!-- Maximum Good Design Guideline -->
            <DesignGuideline
                main_icon="icon_good"
                headline="{$_('design_guidelines.maximum_good.headline_1')}<br>{$_('design_guidelines.maximum_good.headline_2')}"
                subheadings={[
                    {
                        icon: "icon_open_source",
                        heading: $_('design_guidelines.maximum_good.open_source'),
                    },
                    {
                        icon: "icon_ai",
                        heading: $_('design_guidelines.maximum_good.provider_independent'),
                    },
                    {
                        icon: "icon_chat",
                        heading: $_('design_guidelines.maximum_good.chat_anywhere'),
                    }
                ]}
                text={$_('design_guidelines.maximum_good.text')}
                subtext={$_('design_guidelines.maximum_good.subtext')}
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