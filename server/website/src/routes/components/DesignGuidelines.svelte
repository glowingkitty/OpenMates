<script lang="ts">
    // Import the individual DesignGuideline component
    import DesignGuideline from './DesignGuideline.svelte';
    import LargeSeparator from '../components/LargeSeparator.svelte';

    // Export a prop to allow customizing the section title
    export let sectionTitle = "Design Guidelines";
</script>

<LargeSeparator reverse_direction={true} />
<section class="centered gradient-section">
    <h3 style="margin-top: 30px">{sectionTitle}</h3>

    <!-- Privacy Design Guideline -->
    <DesignGuideline
        main_icon="icon_lock"
        headline="<mark>Your privacy matters</mark>"
        subheadings={[
            {
                icon: "icon_anonym",
                heading: "Anonymization",
                link: "/docs/design_guidelines"
            },
            {
                icon: "icon_laptop",
                heading: "Local processing first",
                link: "/docs/design_guidelines"
            },
            {
                icon: "icon_server",
                heading: "Self hosting option",
                link: "/docs/design_guidelines"
            }
        ]}
        text="In today's turbulent world, where profit-at-all-costs companies frequently misuse user data, where companies with inadequate security measures are regularly hacked and their users' data falls into the hands of bad actors, and where we cannot always rely on governments to protect the rights and well-being of their citizens, making decisions to safeguard your privacy has become increasingly essential."
        subtext="Therefore,<br>OpenMates is designed<br>with a focus on privacy."
    />

    <!-- Separator line -->
    <div class="separator"></div>

    <!-- Maximum Good Design Guideline -->
    <DesignGuideline
        main_icon="icon_good"
        headline="<mark>Maximum good,</mark><br>not maximum greed."
        subheadings={[
            {
                icon: "icon_open_source",
                heading: "Open Source",
                link: "/docs/design_guidelines"
            },
            {
                icon: "icon_ai",
                heading: "Provider independent",
                link: "/docs/design_guidelines"
            },
            {
                icon: "icon_chat",
                heading: "Chat anywhere",
                link: "/docs/design_guidelines"
            }
        ]}
        text="Over recent years, profit-at-all-cost tech monopolies have over and over again prioritized their greed instead of the interests of their users and our planet, ignoring the negative consequences and destruction caused by those decisions. We can't just continue like that."
        subtext="Therefore,<br>OpenMates is designed<br>with a focus on maximizing the positive impact of AI."
    />
</section>
<LargeSeparator />

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
        background: var(--color-background-grey);
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