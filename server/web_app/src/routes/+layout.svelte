<script>
    import '@website-styles/buttons.css';
    import '@website-styles/colors.css';
    import '@website-styles/fonts.css';
    import '@website-styles/icons.css';
    import '@website-styles/buttons.css';
    import '@website-styles/fields.css';
    import '@website-styles/cards.css';
    import '@website-styles/chat.css';
    import '@website-styles/mates.css';
    import { replaceOpenMates } from '@website-actions/replaceText';
</script>

<!-- This is where page-specific content will be rendered -->
<main use:replaceOpenMates>
    <slot />
</main>

<style>
</style> 