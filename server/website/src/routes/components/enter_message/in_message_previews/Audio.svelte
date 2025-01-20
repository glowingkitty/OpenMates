<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import PressAndHoldMenu from './PressAndHoldMenu.svelte';
    
    // Props
    export let src: string;
    export let type: 'recording' | 'audio' = 'audio';
    export let title: string | undefined = undefined;
    
    const dispatch = createEventDispatcher();
    
    // Audio player state
    let audio: HTMLAudioElement;
    let isPlaying = false;
    let progress = 0;
    let currentTime = '00:00';
    let duration = '00:00';
    
    // Menu state
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;

    // Initialize audio element
    $: {
        if (src) {
            audio = new Audio(src);
            audio.addEventListener('loadedmetadata', () => {
                duration = formatTime(audio.duration);
            });
            audio.addEventListener('timeupdate', () => {
                progress = (audio.currentTime / audio.duration) * 100;
                currentTime = formatTime(audio.currentTime);
            });
            audio.addEventListener('ended', () => {
                isPlaying = false;
            });
        }
    }

    // Format time in MM:SS
    function formatTime(seconds: number): string {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    // Playback controls
    function togglePlayback() {
        if (isPlaying) {
            audio.pause();
        } else {
            audio.play();
        }
        isPlaying = !isPlaying;
    }

    // Menu handlers
    function handleContextMenu(event: MouseEvent) {
        event.preventDefault();
        showMenu = true;
        menuX = event.clientX;
        menuY = event.clientY;
    }

    function handleDelete() {
        if (audio) {
            audio.pause();
        }
        dispatch('delete');
        showMenu = false;
    }

    function handleDownload() {
        const link = document.createElement('a');
        link.href = src;
        link.download = title || 'audio';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showMenu = false;
    }
</script>

<div class="audio-container" role="button" tabindex="0" on:contextmenu={handleContextMenu}>
    <!-- Left icon -->
    <div class="icon-container">
        <div class="icon_rounded {type === 'recording' ? 'recording' : 'audio'}"></div>
    </div>

    <!-- Content -->
    <div class="content">
        {#if title}
            <div class="title">{title}</div>
        {/if}
        <div class="time">
            {currentTime} {#if isPlaying}/ {duration}{/if}
        </div>
    </div>

    <!-- Progress bar -->
    {#if isPlaying}
        <div class="progress-container">
            <div class="progress-bar" style="width: {progress}%"></div>
        </div>
    {/if}

    <!-- Play button -->
    <button 
        class="play-button"
        on:click={togglePlayback}
        aria-label={isPlaying ? 'Pause' : 'Play'}
    >
        <div class="icon_rounded {isPlaying ? 'pause' : 'play'}"></div>
    </button>
</div>

<PressAndHoldMenu
    show={showMenu}
    x={menuX}
    y={menuY}
    on:close={() => showMenu = false}
    on:delete={handleDelete}
    on:download={handleDownload}
/>

<style>
    .audio-container {
        width: 300px;
        height: 60px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        display: flex;
        align-items: center;
        padding: 0 8px;
        position: relative;
        overflow: hidden;
    }

    .icon-container {
        width: 44px;
        height: 44px;
        margin: 0 8px;
        flex-shrink: 0;
    }

    .content {
        flex-grow: 1;
        margin: 0 8px;
        min-width: 0;
    }

    .title {
        font-size: 14px;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-bottom: 2px;
    }

    .time {
        font-size: 14px;
        color: var(--color-font-secondary);
    }

    .progress-container {
        position: absolute;
        left: 0;
        right: 0;
        top: 0;
        height: 100%;
        background-color: var(--color-grey-30);
        pointer-events: none;
    }

    .progress-bar {
        height: 100%;
        background-color: var(--color-grey-40);
        transition: width 0.1s linear;
    }

    .play-button {
        width: 44px;
        height: 44px;
        margin: 0 8px;
        padding: 0;
        border: none;
        background: none;
        cursor: pointer;
        flex-shrink: 0;
        z-index: 1;
    }
</style>
