<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    export let src: string;
    export let filename: string | null = null;
    export let id: string;
    export let duration: string;
    export let type: 'audio' | 'recording';

    let showCurrentTime = false;
    let currentTime = '00:00';
    let progress = 0;
    let isPlaying = false;
    
    // Add audio element reference
    let audioElement: HTMLAudioElement;
    
    // Initialize audio element when component mounts
    function initAudio() {
        console.log(`Initializing audio player for ${id}`);
        audioElement = new Audio(src);
        
        // Add timeupdate event listener to track progress
        audioElement.addEventListener('timeupdate', () => {
            currentTime = formatTime(audioElement.currentTime);
            progress = (audioElement.currentTime / audioElement.duration) * 100;
        });

        // Add ended event listener to reset state
        audioElement.addEventListener('ended', () => {
            isPlaying = false;
            showCurrentTime = false;
            progress = 0;
            currentTime = '00:00';
        });
    }

    // Format time helper function
    function formatTime(seconds: number): string {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    // Handle play/pause
    function togglePlay() {
        if (!audioElement) {
            initAudio();
        }

        if (isPlaying) {
            console.log(`Pausing audio ${id}`);
            audioElement.pause();
        } else {
            console.log(`Playing audio ${id}`);
            audioElement.play();
        }
        
        isPlaying = !isPlaying;
        showCurrentTime = isPlaying;
    }

    // Clean up on component destroy
    import { onDestroy } from 'svelte';
    onDestroy(() => {
        if (audioElement) {
            audioElement.pause();
            audioElement.remove();
        }
    });

    // Modify the click handler for the play button
    function handlePlayClick(e: MouseEvent) {
        e.stopPropagation();
        togglePlay();
        document.dispatchEvent(new CustomEvent('audioplayclick', { 
            bubbles: true, 
            detail: { id }
        }));
    }

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

<InlinePreviewBase {id} type={type} {src} {filename}>
    {#if type === 'audio' && filename}
        <div class="filename-container">
            <span class="filename">{filename}</span>
        </div>
    {/if}
    <div class="audio-controls">
        <div class="audio-time">
            {#if showCurrentTime}
                <span class="current-time">{currentTime}</span>
            {/if}
            <span class="duration">{duration}</span>
        </div>
        <button 
            class="play-button {isPlaying ? 'playing' : ''}"
            aria-label={isPlaying ? 'Pause' : 'Play'}
            on:click={handlePlayClick}
        ></button>
    </div>
</InlinePreviewBase>

<style>
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
        min-width: 45px;
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
        all: unset;
        right: 10px;
        position: absolute;
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