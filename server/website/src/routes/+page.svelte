<script lang="ts">
    import Icon from './components/Icon.svelte';

    // Define icon groups for left and right sides
    const header_app_icons = [
        // Left side | First column
        [
            {type: 'app', name: 'videos'},
            {type: 'app', name: 'calendar'},
            {type: 'app', name: 'plants'},
            {type: 'app', name: 'shopping'},
            {type: 'app', name: 'study'},
            {type: 'app', name: 'weather'},
            {type: 'app', name: 'travel'}
        ],
        // Left side | Second column
        [
            {type: 'app', name: 'health'},
            {type: 'app', name: 'nutrition'},
            {type: 'app', name: 'fitness'},
            {type: 'app', name: 'jobs'},
            {type: 'app', name: 'home'},
            {type: 'app', name: 'events'},
            {type: 'app', name: 'photos'}
        ],
        // Left side | Third column
        [
            {type: 'app', name: 'web'},
            {type: 'app', name: 'language'},
            {type: 'app', name: 'shipping'},
            {type: 'app', name: 'books'},
            {type: 'app', name: 'tv'},
            {type: 'app', name: 'legal'},
            {type: 'app', name: 'maps'}
        ],
        // Right side | First column
        [
            {type: 'app', name: 'finance'},
            {type: 'app', name: 'code'},
            {type: 'app', name: 'mail'},
            {type: 'app', name: 'hosting'},
            {type: 'app', name: 'notes'},
            {type: 'app', name: 'design'},
            {type: 'app', name: 'slides'}
        ],
        // Right side | Second column
        [
            {type: 'app', name: 'business'},
            {type: 'app', name: 'pcbdesign'},
            {type: 'app', name: 'socialmedia'},
            {type: 'app', name: 'diagrams'},
            {type: 'app', name: 'whiteboards'},
            {type: 'app', name: 'publishing'},
            {type: 'app', name: 'sheets'}
        ],
        // Right side | Third column
        [
            {type: 'app', name: 'files'},
            {type: 'app', name: 'audio'},
            {type: 'app', name: 'messages'},
            {type: 'app', name: 'news'},
            {type: 'app', name: 'projectmanagement'},
            {type: 'app', name: 'pdfeditor'},
            {type: 'app', name: 'docs'}
        ]
    ]

    // Split icons into left and right sides (first 3 columns are left, last 3 are right)
    const leftIcons = header_app_icons.slice(0, 3).flat();
    const rightIcons = header_app_icons.slice(3).flat();
</script>

<div class="landing-container">
    <!-- Left side icons -->
    <div class="icon-grid left">
        {#each header_app_icons.slice(0, 3) as column}
            <div class="icon-column">
                {#each column as icon}
                    <div class="icon-wrapper">
                        <Icon name={icon.name} type={icon.type} />
                    </div>
                {/each}
            </div>
        {/each}
    </div>

    <!-- Empty center space -->
    <div class="center-space">
        <h1 class="text-center">AI Team Mates.<mark><br>For all of us.</mark></h1>
    </div>

    <!-- Right side icons -->
    <div class="icon-grid right">
        {#each header_app_icons.slice(3) as column}
            <div class="icon-column">
                {#each column as icon}
                    <div class="icon-wrapper">
                        <Icon name={icon.name} type={icon.type} />
                    </div>
                {/each}
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
        min-height: 100vh;
    }

    .icon-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        align-content: start;
    }

    .icon-column {
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .icon-column:nth-child(2) {
        transform: translateY(-2rem);
    }

    .icon-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.2;
        transition: opacity 0.3s ease;
        scale: 0.65;
    }

    /* Center content styles */
    .center-space {
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
    }
</style>
