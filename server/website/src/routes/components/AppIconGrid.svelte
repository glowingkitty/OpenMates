<script lang="ts">
    import Icon from './Icon.svelte';

    // Props
    export let side: 'left' | 'right';

    // Define icon groups for both sides
    const header_app_icons: Record<'left' | 'right', Array<Array<{type: 'app' | 'default' | 'skill' | 'provider' | 'focus', name: string}>>> = {
        left: [
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
            ]
        ],
        right: [
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
    };
</script>

<div class="icon-grid {side}">
    {#each header_app_icons[side] as column}
        <div class="icon-column">
            {#each column as icon}
                <div class="icon-wrapper" data-app={icon.name}>
                    <Icon name={icon.name} type={icon.type} in_header={true}/>
                </div>
            {/each}
        </div>
    {/each}
</div>

<style>
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
    }

    /* Mobile styles */
    @media (max-width: 767px) {
        .icon-grid {
            position: absolute;
            top: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            width: auto;
            -webkit-mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 40%, rgba(0,0,0,0) 100%);
            mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 40%, rgba(0,0,0,0) 100%);
        }

        .icon-grid.left {
            right: 50vw;
        }

        .icon-grid.right {
            left: 50vw;
        }

        .icon-grid .icon-column:nth-child(3) {
            display: none;
        }

        .icon-column {
            display: flex;
            flex-direction: row;
            gap: 0.25rem;
            margin-top: 0;
            transform: none;
        }

        .icon-grid.left .icon-column:nth-child(2),
        .icon-grid.right .icon-column:nth-child(2) {
            transform: translateX(24px);
        }

        .icon-wrapper {
            opacity: 0.3;
        }
    }

    @media (max-width: 600px) {
        .icon-grid.left {
            padding-right: 20px;
            margin-right: -20px;
        }
    }
</style> 