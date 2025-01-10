<script lang="ts">
    import Highlight from './Highlight.svelte';
    import { _ } from 'svelte-i18n';
    export let target: string = '';
</script>

<!-- Add all highlights here -->
{#if target === 'for_all'}
<Highlight
    sub_heading="Ask"
    main_heading={`<mark>${$_('highlight.sections.ask.main_heading_1.text')}</mark><br>${$_('highlight.sections.ask.main_heading_2.text')}`}
    paragraph={`${$_('highlight.sections.ask.paragraph.text')}`}
    text_side="left"
    {target}
/>
<Highlight
    sub_heading="Tasks"
    main_heading={`${$_('highlight.sections.tasks.main_heading_1.text')}<br><mark>${$_('highlight.sections.tasks.main_heading_2.text')}</mark>`}
    paragraph={`${$_('highlight.sections.tasks.paragraph.text')}`}
    text_side="right"
    {target}
/>
<Highlight
    sub_heading="Apps"
    main_heading={`<mark>${$_('highlight.sections.apps.main_heading_1.text')}</mark><br>${$_('highlight.sections.apps.main_heading_2.text')}`}
    paragraph={`${$_('highlight.sections.apps.paragraph.text')}`}
    text_side="left"
    {target}
/>
{/if}
{#if target === 'for_developers'}
<Highlight
    sub_heading="Ask"
    main_heading={`<mark>${$_('highlight.sections.ask.main_heading.text')}</mark>`}
    paragraph={`${$_('highlight.sections.ask.paragraph.text')}`}
    text_side="left"
    target="for_developers"
/>
<Highlight
    sub_heading="Tasks"
    main_heading={`<mark>${$_('highlight.sections.tasks.main_heading.text')}</mark>`}
    paragraph={`${$_('highlight.sections.tasks.paragraph.text')}`}
    text_side="right"
    target="for_developers"
/>
<Highlight
    sub_heading="Apps"
    main_heading={`<mark>${$_('highlight.sections.apps.main_heading.text')}</mark>`}
    paragraph={`${$_('highlight.sections.apps.paragraph.text')}`}
    text_side="left"
    target="for_developers"
/>
{/if}
