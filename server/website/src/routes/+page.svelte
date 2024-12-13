<script lang="ts">
    import Icon from './components/Icon.svelte';

    // Define icon groups for left and right sides
    const leftIcons = [
        {type: 'app', name: 'videos'},
        {type: 'app', name: 'calendar'},
        {type: 'app', name: 'plants'},
        {type: 'app', name: 'shopping'},
        {type: 'app', name: 'study'},
        {type: 'app', name: 'weather'},
        {type: 'app', name: 'travel'},
        {type: 'app', name: 'health'},
        {type: 'app', name: 'nutrition'},
        {type: 'app', name: 'fitness'},
        {type: 'app', name: 'jobs'},
        {type: 'app', name: 'home'},
        {type: 'app', name: 'events'},
        {type: 'app', name: 'photos'},
        {type: 'app', name: 'web'},
        {type: 'app', name: 'language'},
        {type: 'app', name: 'shipping'},
        {type: 'app', name: 'books'},
        {type: 'app', name: 'tv'},
        {type: 'app', name: 'legal'},
        {type: 'app', name: 'maps'}
    ];

    const rightIcons = [
        {type: 'app', name: 'finance'},
        {type: 'app', name: 'code'},
        {type: 'app', name: 'mail'},
        {type: 'app', name: 'hosting'},
        {type: 'app', name: 'notes'},
        {type: 'app', name: 'design'},
        {type: 'app', name: 'slides'},
        {type: 'app', name: 'business'},
        {type: 'app', name: 'pcbdesign'},
        {type: 'app', name: 'socialmedia'},
        {type: 'app', name: 'diagrams'},
        {type: 'app', name: 'whiteboards'},
        {type: 'app', name: 'publishing'},
        {type: 'app', name: 'sheets'},
        {type: 'app', name: 'files'},
        {type: 'app', name: 'audio'},
        {type: 'app', name: 'messages'},
        {type: 'app', name: 'news'},
        {type: 'app', name: 'projectmanagement'},
        {type: 'app', name: 'pdfeditor'},
        {type: 'app', name: 'docs'}
    ];
</script>

<div class="landing-container">
    <!-- Left side icons -->
    <div class="icon-grid left">
        {#each leftIcons as icon}
            <div class="icon-wrapper">
                <Icon name={icon.name} type={icon.type} />
            </div>
        {/each}
    </div>

    <!-- Empty center space -->
    <div class="center-space">
        <h1 class="text-center">AI Team Mates.<mark><br>For all of us.</mark></h1>
    </div>

    <!-- Right side icons -->
    <div class="icon-grid right">
        {#each rightIcons as icon}
            <div class="icon-wrapper">
                <Icon name={icon.name} type={icon.type} />
            </div>
        {/each}
    </div>
</div>



<style>
    .landing-container {
        display: grid;
        grid-template-columns: 250px 1fr 250px;
        max-width: 1400px;
        margin: 0 auto;
        padding: 2rem;
        min-height: 100vh;
    }

    .icon-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 1rem;
        padding: 1rem;
        align-content: center;
    }

    .icon-grid .icon-wrapper:nth-child(3n-1) {
        transform: translateY(-2rem);
    }

    .icon-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.3;
        transition: opacity 0.3s ease;
        scale: 0.7;
    }

    .icon-wrapper:hover {
        opacity: 0.8;
    }

    /* Responsive adjustments */
    @media (max-width: 1024px) {
        .landing-container {
            grid-template-columns: 1fr;
        }

        .icon-grid {
            display: none;
        }
    }
</style>
