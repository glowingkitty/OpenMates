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
    let videoHeight = 0;

    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.debug('[Video]', ...args),
        info: (...args: any[]) => console.info('[Video]', ...args)
    };

    // Convert duration string (MM:SS) to seconds
    function getDurationInSeconds(timeStr: string): number {
        // Handle invalid duration string
        if (!timeStr || timeStr.includes('Infinity') || timeStr.includes('NaN')) {
            return 0;
        }
        const [minutes, seconds] = timeStr.split(':').map(Number);
        return minutes * 60 + seconds;
    }

    // Format seconds to MM:SS
    function formatTime(seconds: number): string {
        if (!isFinite(seconds) || isNaN(seconds)) {
            return '00:00';
        }
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    // Initialize video element and load metadata
    async function initVideo() {
        logger.debug(`Initializing video player for ${id}`, {
            initialDuration: duration,
            src
        });

        if (!videoElement) {
            videoElement = document.createElement('video');
            videoElement.src = src;
            videoElement.preload = 'metadata';

            // Wait for metadata to load to get actual duration
            await new Promise((resolve) => {
                videoElement.addEventListener('loadedmetadata', () => {
                    logger.debug(`Video metadata loaded, using passed duration: ${duration}`);

                    // Set video height based on aspect ratio
                    videoHeight = (videoElement.videoHeight / videoElement.videoWidth) * 300;
                    thumbnailLoaded = true;
                    resolve(null);
                });
            });

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
                videoElement.currentTime = 0; // Reset video position to start
                logger.debug('Video playback ended, reset to beginning');
            });

            // Add loadeddata event listener to double-check duration
            videoElement.addEventListener('loadeddata', () => {
                logger.debug('Video data loaded:', {
                    duration: videoElement.duration,
                    readyState: videoElement.readyState,
                    currentSrc: videoElement.currentSrc
                });

                // Update duration again if it's valid now
                if (isFinite(videoElement.duration) && videoElement.duration > 0) {
                    duration = formatTime(videoElement.duration);
                    logger.debug(`Updated video duration to ${duration} after data load`);
                }
            });

            // Add error listener
            videoElement.addEventListener('error', (e) => {
                logger.debug('Video error:', {
                    error: videoElement.error,
                    event: e
                });
            });
        }
    }

    // Handle play/pause with better error handling
    async function togglePlay(e: MouseEvent) {
        e.stopPropagation();
        
        try {
            if (!videoElement) {
                await initVideo();
            }

            if (isPlaying) {
                logger.debug(`Pausing video ${id}`);
                await videoElement.pause();
            } else {
                logger.debug(`Playing video ${id}`);
                const playResult = await videoElement.play();
                logger.debug('Play result:', playResult);
            }
            
            isPlaying = !isPlaying;
            showCurrentTime = isPlaying;
        } catch (err) {
            logger.debug('Error toggling video playback:', err);
        }
    }

    // Initialize on mount
    initVideo();

    // Clean up on component destroy
    onDestroy(() => {
        if (videoElement) {
            videoElement.pause();
            videoElement.remove();
        }
    });
</script>

<InlinePreviewBase {id} type="video" {src} {filename} height="200px">
    <div class="video-container">
        {#if videoElement}
            <video 
                class="video-element" 
                src={src}
                bind:this={videoElement}
            >
                <track kind="captions" />
            </video>
        {/if}

        <!-- New bottom progress bar that's always visible -->
        <div class="bottom-progress-container">
            <div 
                class="bottom-progress-bar" 
                style="width: {progress}%"
                aria-label="Video playback progress"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={progress}
            ></div>
        </div>

        <!-- Moved play button outside info-bar -->
        <button 
            class="play-button clickable-icon {isPlaying ? 'icon_pause' : 'icon_play'}"
            aria-label={isPlaying ? 'Pause' : 'Play'}
            on:click={togglePlay}
        ></button>

        <!-- Added transition for info-bar -->
        <div class="info-bar" class:hidden={isPlaying}>
            <div 
                class="progress-bar" 
                style="width: {progress}%"
                aria-label="Video playback progress"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={progress}
            ></div>
            {#if showCurrentTime}
                <span class="time-display">
                    <span class="current-time">{currentTime}</span>
                    <span class="time-separator"> / </span>
                    <span class="duration">{duration}</span>
                </span>
            {:else}
                <span class="duration">{duration}</span>
            {/if}
        </div>
    </div>
</InlinePreviewBase>

<style>
    .video-container {
        position: relative;
        width: 300px;
        min-height: 200px;
        background-color: var(--color-grey-20);
        border-radius: 24px;
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

    .info-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        border-radius: 30px;
        height: 60px;
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        padding-left: 70px;
        padding-right: 16px;
        overflow: hidden;
        user-select: none;
        /* Add transition for smooth fade */
        transition: opacity 0.3s ease-in-out;
        opacity: 1;
        z-index: 1;
    }

    .info-bar.hidden {
        opacity: 0;
        pointer-events: none;
    }

    .play-button {
        opacity: 0.5;
        right: 20px;
        bottom: 17px;
        position: absolute;
        width: 25px;
        height: 25px;
        z-index: 2;
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
        background-color: var(--color-grey-10);
        transition: width 0.5s linear;
        /* Make sure progress bar stays behind content */
        z-index: 0;
        opacity: 1;
    }

    .time-display, .duration {
        z-index: 1;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .time-separator {
        opacity: 0.7;
    }

    .current-time, .duration {
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
        font-variant-numeric: tabular-nums;
        min-width: 40px;
    }

    /* New styles for bottom progress bar */
    .bottom-progress-container {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 20px;
        z-index: 1;
    }

    .bottom-progress-bar {
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        width: 0;
        background-color: var(--color-grey-10);
        transition: width 0.5s linear;
        opacity: 0.8;
    }
</style>
