<script lang="ts">
    import Highlight from './Highlight.svelte';
    export let target: 'for_all' | 'developer';
</script>

<!-- Add all highlights here -->
{#if target === 'for_all'}
<Highlight
    sub_heading="Ask"
    main_heading="<mark>Your personalized experts</mark><br> for your questions."
    paragraph="For example:<br>Get career advice<br>based on your interests."
    text_side="left"
/>
<Highlight
    sub_heading="Tasks"
    main_heading="Ask them to<br><mark>fulfill your tasks</mark><br>using apps."
    paragraph="For example:<br>Find doctor appointments<br>on Doctolib & Jameda."
    text_side="right"
/>
<Highlight
    sub_heading="Apps"
    main_heading="<mark>So many apps</mark><br>to transform your<br>personal life & work."
    paragraph="For example:<br>Find events<br>on Meetup, Eventbrite & RA."
    text_side="left"
/>
{/if}

<!-- chat_example=[
                    {
                        type: 'user',
                        text: 'I am unhappy in my current job. Any ideas in what direction I could go instead?',
                        waitTime: 2000
                    },
                    {
                        type: 'started_focus',
                        appNames: ['Jobs'],
                        focusName: 'Career insights',
                        focusIcon: 'insights',
                        waitTime: 500
                    },
                    {
                        type: 'loaded_preferences',
                        appNames: ['Jobs'],
                        waitTime: 500
                    },
                    {
                        type: 'mate',
                        mateName: 'Burton',
                        text: 'Of course! Since you mentioned that you have a background in marketing and enjoy storytelling, we could look for roles that leverage those skills.\n\nTo get a better sense of direction, could you tell me:\n1. What aspects of your previous jobs did you find most fulfilling?',
                        waitTime: 3000
                    }
                ] -->