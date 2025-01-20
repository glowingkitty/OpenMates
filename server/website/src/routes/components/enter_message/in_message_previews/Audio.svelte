<script lang="ts">
    export let src: string;
    export let filename: string | null = null;
    export let id: string;
    export let duration: string;
    export let type: 'audio' | 'recording';

    let currentTime = '00:00';
    let progress = 0;
    let isPlaying = false;

    function handleClick(e: MouseEvent) {
        document.dispatchEvent(new CustomEvent('embedclick', { 
            bubbles: true, 
            detail: { 
                id,
                elementId: `embed-${id}`
            }
        }));
    }
</script>

<div 
    class="preview-container audio"
    role="button"
    tabindex="0"
    data-type="custom-embed"
    data-src={src}
    data-filename={filename}
    data-id={id}
    data-embed-type={type}
    data-duration={duration}
    id="embed-{id}"
    on:click={handleClick}
    on:keydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleClick(e as unknown as MouseEvent);
        }
    }}
>
    <div class="icon_rounded {type}"></div>
    {#if type === 'audio' && filename}
        <div class="filename-container">
            <span class="filename">{filename}</span>
        </div>
    {/if}
    <div class="audio-controls">
        <div class="audio-time">
            <span class="current-time">{currentTime}</span>
            <span class="duration">{duration}</span>
        </div>
        <div class="progress-bar">
            <div class="progress" style="width: {progress}%"></div>
        </div>
        <button 
            class="play-button {isPlaying ? 'playing' : ''}"
            aria-label={isPlaying ? 'Pause' : 'Play'}
            on:click|stopPropagation={() => {
                isPlaying = !isPlaying;
                document.dispatchEvent(new CustomEvent('audioplayclick', { 
                    bubbles: true, 
                    detail: { id }
                }));
            }}
        ></button>
    </div>
</div>

<style>
    .preview-container {
        width: 300px;
        height: 60px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        display: flex;
        align-items: center;
        margin: 4px 0;
        padding-right: 16px;
    }

    .preview-container:hover {
        background-color: var(--color-grey-30);
    }

    .filename-container {
        flex: 1;
        margin-left: 65px;
        margin-right: 16px;
        min-height: 40px;
        display: flex;
        align-items: center;
    }

    .audio-controls {
        flex: 1;
        margin-left: 65px;
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .audio-time {
        display: flex;
        gap: 8px;
        font-size: 12px;
        color: var(--color-font-secondary);
        white-space: nowrap;
    }

    .progress-bar {
        flex: 1;
        height: 4px;
        background-color: var(--color-grey-40);
        border-radius: 2px;
        overflow: hidden;
    }

    .progress {
        height: 100%;
        background-color: var(--color-app-audio);
        transition: width 0.1s linear;
    }

    .play-button {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: none;
        background-color: var(--color-app-audio);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        transition: background-color 0.2s;
    }

    .play-button::before {
        content: '';
        width: 0;
        height: 0;
        border-style: solid;
        border-width: 8px 0 8px 12px;
        border-color: transparent transparent transparent white;
        margin-left: 2px;
    }

    .play-button.playing::before {
        width: 12px;
        height: 12px;
        border: none;
        margin: 0;
        border-style: double;
        border-width: 0 0 0 12px;
        border-color: white;
    }

    .play-button:hover {
        background-color: var(--color-app-audio-hover);
    }
</style> 