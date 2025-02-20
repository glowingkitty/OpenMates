<script lang="ts">
    import { fade } from 'svelte/transition';
    export let currentStep: number;
    export let totalSteps = 10;

    $: steps = Array.from({ length: totalSteps }, (_, i) => i + 1);
</script>

<div class="status-bar" transition:fade>
    {#each steps as step}
        <div class="status-dot" class:active={step === currentStep}></div>
    {/each}
</div>

<style>
    .status-bar {
        display: flex;
        gap: 5px;
        justify-content: center;
        padding: 16px 0;
    }

    .status-dot {
        width: 15px;
        height: 15px;
        border-radius: 50%;
        background-color: var(--color-grey-30);
        transition: background-color 0.3s ease;
    }

    .status-dot.active {
        background-color: var(--color-grey-50);
    }
</style>
