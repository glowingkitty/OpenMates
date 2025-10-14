<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { _ } from 'svelte-i18n';
    
    // Props using Svelte 5 runes
    let { 
        src,
        filename = null,
        id,
        duration,
        type
    }: {
        src: string;
        filename?: string | null;
        id: string;
        duration: string; // Format: "MM:SS"
        type: 'audio' | 'recording';
    } = $props();

    let showCurrentTime = false;
    let currentTime = '00:00';
    let progress = 0;
    let isPlaying = false;
    
    // Add audio element reference
    let audioElement: HTMLAudioElement;
    
    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.debug('[Audio]', ...args),
        info: (...args: any[]) => console.info('[Audio]', ...args)
    };

    // Convert duration string (MM:SS) to seconds
    function getDurationInSeconds(timeStr: string): number {
        const [minutes, seconds] = timeStr.split(':').map(Number);
        return minutes * 60 + seconds;
    }

    // Format seconds to MM:SS
    function formatTime(seconds: number): string {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    // Initialize audio element when component mounts
    function initAudio() {
        logger.debug(`Initializing audio player for ${id}`);
        audioElement = new Audio(src);

        // Add timeupdate event listener to track progress
        audioElement.addEventListener('timeupdate', () => {
            const durationInSeconds = getDurationInSeconds(duration);
            currentTime = formatTime(audioElement.currentTime);
            progress = (audioElement.currentTime / durationInSeconds) * 100;
        });

        // Add ended event listener to reset state
        audioElement.addEventListener('ended', () => {
            isPlaying = false;
            showCurrentTime = false;
            progress = 0;
            currentTime = '00:00';
        });
    }

    // Handle play/pause
    function togglePlay() {
        if (!audioElement) {
            initAudio();
        }

        if (isPlaying) {
            logger.debug(`Pausing audio ${id}`);
            audioElement.pause();
        } else {
            logger.debug(`Playing audio ${id}`);
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
</script>

<InlinePreviewBase {id} type={type} {src} {filename}>
    <div 
        class="progress-bar" 
        style="width: {progress}%"
        aria-label={$_('audio.playback_progress.text')}
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={progress}
    ></div>
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
            class="play-button clickable-icon {isPlaying ? 'icon_pause' : 'icon_play'}"
            aria-label={isPlaying ? $_('audio.pause.text') : $_('audio.play.text')}
            onclick={handlePlayClick}
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

    .play-button {
        opacity: 0.5;
        right: 20px;
        position: absolute;
        width: 25px;
        height: 25px;
    }

    .progress-bar {
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        width: 0;
        background-color: var(--color-grey-10);
        transition: width 0.5s linear;
        /* Make sure progress bar stays behind content */
        z-index: 0;
        opacity: 1;
    }

    /* Ensure other elements stay above progress bar */
    .audio-controls {
        position: relative;
        z-index: 1;
    }

    .filename-container {
        position: relative;
        z-index: 1;
    }
</style> 