<script lang="ts">
    // Import the individual DesignGuideline component
    import DesignGuideline from './DesignGuideline.svelte';

    // Export a prop to allow customizing the section title
    export let sectionTitle = "Design Guidelines";
</script>

<section class="centered">
    <h3>{sectionTitle}</h3>

    <!-- Privacy Design Guideline -->
    <DesignGuideline
        main_icon="icon_lock"
        headline="<mark>Your privacy matters</mark>"
        subheadings={[
            {
                icon: "icon_anonym",
                heading: "Anonymization",
                link: "/docs/design_guidelines#anonymization"
            },
            {
                icon: "icon_laptop",
                heading: "Local processing first",
                link: "/docs/design_guidelines#local-processing"
            },
            {
                icon: "icon_server",
                heading: "Self hosting option",
                link: "/docs/design_guidelines#self-hosting"
            }
        ]}
        text="In today's turbulent world, where profit-at-all-costs companies frequently misuse user data, where companies with inadequate security measures are regularly hacked and their users' data falls into the hands of bad actors, and where we cannot always rely on governments to protect the rights and well-being of their citizens, making decisions to safeguard your privacy has become increasingly essential."
        subtext="Therefore, OpenMates is designed with a focus on privacy."
    />

    <!-- Maximum Good Design Guideline -->
    <DesignGuideline
        main_icon="icon_good"
        headline="<mark>Maximum good,</mark><br>not maximum greed."
        subheadings={[
            {
                icon: "icon_open_source",
                heading: "Open Source",
                link: "/docs/design_guidelines#open-source"
            },
            {
                icon: "icon_ai",
                heading: "Provider independent",
                link: "/docs/design_guidelines#provider-independence"
            },
            {
                icon: "icon_chat",
                heading: "Chat anywhere",
                link: "/docs/design_guidelines#chat-anywhere"
            }
        ]}
        text="Over recent years, profit-at-all-cost tech monopolies have over and over again prioritized their greed instead of the interests of their users and our planet, ignoring the negative consequences and destruction caused by those decisions. We can't just continue like that."
        subtext="Therefore, OpenMates is designed with a focus on maximizing the positive impact of AI."
    />
</section>

<style>
    .centered {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2rem;
        padding: 2rem;
    }

    h3 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 600;
    }
</style> 