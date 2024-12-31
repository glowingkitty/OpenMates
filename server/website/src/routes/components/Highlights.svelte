<script lang="ts">
    import Highlight from './Highlight.svelte';
    export let target: string = '';
</script>

<!-- Add all highlights here -->
{#if target === 'for_all'}
<Highlight
    sub_heading="Ask"
    main_heading="<mark>Your personalized experts</mark><br> for your questions."
    paragraph="For example:<br>Get career advice<br>based on your interests."
    text_side="left"
    {target}
/>
<Highlight
    sub_heading="Tasks"
    main_heading="Ask them to<br><mark>fulfill your tasks</mark><br>using apps."
    paragraph="For example:<br>Find doctor appointments<br>that don’t collide with your calendar<br>on Doctolib & Jameda."
    text_side="right"
    {target}
/>
<Highlight
    sub_heading="Apps"
    main_heading="<mark>So many apps</mark><br>to transform your<br>personal life & work."
    paragraph="For example:<br>Find events<br>on Meetup, Eventbrite & RA."
    text_side="left"
    {target}
/>
{/if}
{#if target === 'for_developers'}
<Highlight
    sub_heading="Ask"
    main_heading="<mark>Your personalized experts</mark><br> for your questions."
    paragraph="For example:<br>Get career advice<br>based on your interests."
    text_side="left"
    target="for_developers"
/>
<Highlight
    sub_heading="Tasks"
    main_heading="Ask them to<br><mark>fulfill your tasks</mark><br>using apps."
    paragraph="For example:<br>Find doctor appointments<br>that don’t collide with your calendar<br>on Doctolib & Jameda."
    text_side="right"
    target="for_developers"
/>
<Highlight
    sub_heading="Apps"
    main_heading="<mark>So many apps</mark><br>to transform your<br>personal life & work."
    paragraph="For example:<br>Find events<br>on Meetup, Eventbrite & RA."
    text_side="left"
    target="for_developers"
/>
{/if}
