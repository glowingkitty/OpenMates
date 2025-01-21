<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onDestroy } from 'svelte';
    
    export let src: string;
    export let filename: string | null = null;
    export let id: string;
    export let duration: string; // Format: "MM:SS"

    let videoElement: HTMLVideoElement;
    let isPlaying = false;
    let showCurrentTime = false;
    let currentTime = '00:00';
    let progress = 0;
    let thumbnailLoaded = false;

    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.debug('[Video]', ...args),
        info: (...args: any[]) => console.info('[Video]', ...args)
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

    // Initialize video element
    function initVideo() {
        logger.debug(`Initializing video player for ${id}`);
        if (!videoElement) {
            videoElement = document.createElement('video');
            videoElement.src = src;
            videoElement.preload = 'metadata';

            // Add timeupdate event listener to track progress
            videoElement.addEventListener('timeupdate', () => {
                const durationInSeconds = getDurationInSeconds(duration);
                currentTime = formatTime(videoElement.currentTime);
                progress = (videoElement.currentTime / durationInSeconds) * 100;
            });

            // Add ended event listener to reset state
            videoElement.addEventListener('ended', () => {
                isPlaying = false;
                showCurrentTime = false;
                progress = 0;
                currentTime = '00:00';
            });

            // Load thumbnail
            videoElement.addEventListener('loadeddata', () => {
                thumbnailLoaded = true;
            });
        }
    }

    // Handle play/pause
    function togglePlay(e: MouseEvent) {
        e.stopPropagation();
        
        if (!videoElement) {
            initVideo();
        }

        if (isPlaying) {
            logger.debug(`Pausing video ${id}`);
            videoElement.pause();
        } else {
            logger.debug(`Playing video ${id}`);
            videoElement.play();
        }
        
        isPlaying = !isPlaying;
        showCurrentTime = isPlaying;

        // Dispatch custom event for video play
        document.dispatchEvent(new CustomEvent('videoplayclick', { 
            bubbles: true, 
            detail: { id }
        }));
    }

    // Clean up on component destroy
    onDestroy(() => {
        if (videoElement) {
            videoElement.pause();
            videoElement.remove();
        }
    });
</script>

<InlinePreviewBase {id} type="video" {src} {filename}>
    <div class="video-container">
        {#if videoElement}
            <video 
                class="video-element" 
                src={src}
                bind:this={videoElement}
                poster={src + '?thumbnail=true'}
            >
                <track kind="captions" src="" label="English" />
            </video>
        {/if}
        <div 
            class="progress-bar" 
            style="width: {progress}%"
            aria-label="Video playback progress"
            role="progressbar"
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow={progress}
        ></div>
        <div class="video-controls">
            <div class="time-display">
                {#if showCurrentTime}
                    <span class="current-time">{currentTime}</span>
                {/if}
                <span class="duration">{duration}</span>
            </div>
            <button 
                class="play-button clickable-icon {isPlaying ? 'icon_pause' : 'icon_play'}"
                aria-label={isPlaying ? 'Pause' : 'Play'}
                on:click={togglePlay}
            ></button>
        </div>
    </div>
</InlinePreviewBase>

<style>
    .video-container {
        position: relative;
        width: 100%;
        height: 100%;
        background-color: var(--color-grey-20);
        border-radius: 8px;
        overflow: hidden;
    }

    .video-element {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .video-controls {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 60px;
        padding: 0 20px 0 70px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: linear-gradient(transparent, rgba(0, 0, 0, 0.5));
        z-index: 2;
    }

    .time-display {
        display: flex;
        gap: 8px;
        font-size: 12px;
        color: var(--color-font-primary);
        white-space: nowrap;
        min-width: 45px;
    }

    .play-button {
        opacity: 0.8;
        width: 25px;
        height: 25px;
        transition: opacity 0.2s;
    }

    .play-button:hover {
        opacity: 1;
    }

    .progress-bar {
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        width: 0;
        background-color: rgba(255, 255, 255, 0.2);
        transition: width 0.5s linear;
        z-index: 1;
    }

    .current-time, .duration {
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    }
</style>
