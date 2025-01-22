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

    // Add supported video formats
    const SUPPORTED_VIDEO_FORMATS = [
        'video/mp4',
        'video/webm',
        'video/ogg',
        'video/quicktime', // .mov files
        'video/x-m4v',     // .m4v files
        'video/x-matroska', // .mkv files
        'video/x-msvideo',  // .avi files
        'video/3gpp',      // .3gp files
        'video/x-ms-wmv'   // .wmv files
    ];

    // Add function to check video playability
    async function isVideoPlayable(videoElement: HTMLVideoElement): Promise<boolean> {
        try {
            // Check if the video metadata can be loaded
            await new Promise((resolve, reject) => {
                const timeoutId = setTimeout(() => {
                    reject(new Error('Timeout loading video metadata'));
                }, 5000); // 5 second timeout

                const handleLoaded = () => {
                    clearTimeout(timeoutId);
                    videoElement.removeEventListener('loadedmetadata', handleLoaded);
                    videoElement.removeEventListener('error', handleError);
                    resolve(true);
                };

                const handleError = (error: Event) => {
                    clearTimeout(timeoutId);
                    videoElement.removeEventListener('loadedmetadata', handleLoaded);
                    videoElement.removeEventListener('error', handleError);
                    reject(error);
                };

                videoElement.addEventListener('loadedmetadata', handleLoaded);
                videoElement.addEventListener('error', handleError);
            });

            // Try to play the video (some browsers require this)
            await videoElement.play();
            await videoElement.pause();
            videoElement.currentTime = 0;
            
            return true;
        } catch (error) {
            logger.debug('Video playability check failed:', error);
            return false;
        }
    }

    // Update initVideo function with better timeout handling and .mov support
    async function initVideo() {
        logger.debug(`Initializing video player for ${id}`, {
            initialDuration: duration,
            src
        });

        try {
            if (!videoElement) {
                videoElement = document.createElement('video');
                videoElement.src = src;
                videoElement.preload = 'metadata';

                // For .mov files specifically, we need to be more patient
                const isMovFile = filename?.toLowerCase().endsWith('.mov');
                const timeoutDuration = isMovFile ? 30000 : 10000; // 30 seconds for .mov, 10 for others

                // Create a promise that resolves when either metadata or data is loaded
                const metadataPromise = new Promise<void>((resolve) => {
                    let durationFound = false;

                    const checkDuration = () => {
                        if (isFinite(videoElement.duration) && videoElement.duration > 0) {
                            duration = formatTime(videoElement.duration);
                            logger.debug('Duration found:', duration);
                            durationFound = true;
                            resolve();
                        }
                    };

                    videoElement.addEventListener('loadedmetadata', () => {
                        logger.debug('Metadata loaded, checking duration...');
                        checkDuration();

                        // Update video height based on aspect ratio
                        videoHeight = (videoElement.videoHeight / videoElement.videoWidth) * 300;
                        thumbnailLoaded = true;
                    });

                    videoElement.addEventListener('durationchange', () => {
                        logger.debug('Duration changed, checking...');
                        checkDuration();
                    });

                    videoElement.addEventListener('loadeddata', () => {
                        logger.debug('Data loaded, checking duration...');
                        checkDuration();
                    });

                    // For .mov files, try to force duration calculation
                    if (isMovFile) {
                        videoElement.addEventListener('canplay', () => {
                            logger.debug('Can play, checking duration...');
                            if (!durationFound) {
                                // Try seeking to end to force duration calculation
                                videoElement.currentTime = 24 * 60 * 60; // Seek to 24 hours
                                setTimeout(() => {
                                    checkDuration();
                                    videoElement.currentTime = 0;
                                }, 100);
                            }
                        });
                    }
                });

                // Wait for metadata with timeout
                await Promise.race([
                    metadataPromise,
                    new Promise((_, reject) => {
                        setTimeout(() => {
                            if (!isFinite(videoElement.duration) || videoElement.duration === 0) {
                                reject(new Error(`Video metadata timeout after ${timeoutDuration}ms`));
                            }
                        }, timeoutDuration);
                    })
                ]);

                // Add existing event listeners
                videoElement.addEventListener('timeupdate', () => {
                    const videoDuration = videoElement.duration;
                    if (isFinite(videoDuration) && videoDuration > 0) {
                        currentTime = formatTime(videoElement.currentTime);
                        progress = (videoElement.currentTime / videoDuration) * 100;
                    }
                });

                videoElement.addEventListener('ended', () => {
                    isPlaying = false;
                    showCurrentTime = false;
                    progress = 0;
                    currentTime = '00:00';
                    videoElement.currentTime = 0;
                    logger.debug('Video playback ended');
                });

                videoElement.addEventListener('loadeddata', () => {
                    logger.debug('Video data loaded:', {
                        duration: videoElement.duration,
                        readyState: videoElement.readyState,
                        currentSrc: videoElement.currentSrc
                    });

                    if (isFinite(videoElement.duration) && videoElement.duration > 0) {
                        duration = formatTime(videoElement.duration);
                        logger.debug(`Updated video duration to ${duration}`);
                    }
                });

                // Enhanced error handling
                videoElement.addEventListener('error', (e) => {
                    const error = videoElement.error;
                    logger.debug('Video error:', {
                        code: error?.code,
                        message: error?.message,
                        event: e
                    });

                    // Show user-friendly error message
                    if (error?.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
                        // Handle unsupported format
                        logger.debug('Video format not supported');
                    } else if (error?.code === MediaError.MEDIA_ERR_NETWORK) {
                        // Handle network error
                        logger.debug('Network error while loading video');
                    }
                });
            }
        } catch (error) {
            logger.debug('Error initializing video:', error);
            // Don't throw the error, just log it and continue
            // This allows the video to still be displayed even if duration isn't immediately available
        }
    }

    // Update getDurationInSeconds to handle video element duration
    function getDurationInSeconds(timeStr: string): number {
        // First check if we have a valid duration from the video element
        if (videoElement && isFinite(videoElement.duration) && videoElement.duration > 0) {
            return videoElement.duration;
        }
        
        // Handle invalid duration string
        if (!timeStr || timeStr.includes('Infinity') || timeStr.includes('NaN')) {
            return 0;
        }
        const [minutes, seconds] = timeStr.split(':').map(Number);
        return minutes * 60 + seconds;
    }

    // Update formatTime to handle edge cases better
    function formatTime(seconds: number): string {
        if (!isFinite(seconds) || isNaN(seconds)) {
            return '00:00';
        }
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
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

<InlinePreviewBase 
    {id} 
    type="video" 
    {src} 
    {filename} 
    height="200px"
    customClass={`${isPlaying ? 'playing' : ''} ${videoElement?.error ? 'error' : ''}`}
>
    <div class="video-container">
        {#if videoElement}
            <video 
                class="video-element" 
                src={src}
                bind:this={videoElement}
                on:error={() => logger.debug('Video element error event triggered')}
            >
                <track kind="captions" />
            </video>
        {/if}

        <!-- Show error message if video fails to load -->
        {#if videoElement?.error}
            <div class="error-message">
                <span class="icon_error"></span>
                <span>Video format not supported</span>
            </div>
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

        <!-- Update the info-bar section -->
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
            <div class="text-container">
                {#if filename}
                    <span class="filename">{filename}</span>
                {/if}
                <span class="time-info">
                    {#if showCurrentTime}
                        <span class="current-time">{currentTime}</span>
                        <span class="time-separator"> / </span>
                    {/if}
                    <span class="duration">{duration}</span>
                </span>
            </div>
        </div>

        <!-- Play button outside info-bar -->
        <button 
            class="play-button clickable-icon {isPlaying ? 'icon_pause' : 'icon_play'}"
            aria-label={isPlaying ? 'Pause' : 'Play'}
            on:click={togglePlay}
        ></button>
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
        transition: opacity 0.3s ease-in-out;
        opacity: 1;
        z-index: 1;
    }

    .info-bar.hidden {
        opacity: 0;
        pointer-events: none;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
        line-height: 1.3;
        z-index: 1;
        flex: 1;
        min-width: 0;
        max-width: calc(100% - 40px);
        padding-right: 16px;
        transition: opacity 0.3s ease-in-out;
    }

    .text-container.hidden {
        opacity: 0;
        pointer-events: none;
    }

    .play-button {
        position: absolute;
        bottom: 17px;
        right: 20px;
        opacity: 0.5;
        width: 25px;
        height: 25px;
        z-index: 2;
        transition: opacity 0.2s ease;
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
        z-index: 0;
        opacity: 1;
    }

    .filename {
        font-size: 14px;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block; /* Ensure the element takes full width */
    }

    .time-info {
        font-size: 14px;
        color: var(--color-font-secondary);
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .current-time, .duration {
        font-variant-numeric: tabular-nums;
    }

    .time-separator {
        opacity: 0.7;
    }

    /* New styles for bottom progress bar */
    .bottom-progress-container {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 10px;
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

    /* Hide the icon_rounded when video is playing */
    :global(.preview-container.playing .icon_rounded) {
        display: none;
    }

    /* Add error state styles */
    .error-message {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        color: var(--color-error);
        text-align: center;
        padding: 16px;
    }

    .error-message span {
        font-size: 14px;
    }

    :global(.preview-container.error .icon_rounded) {
        opacity: 0.3;
    }

    :global(.preview-container.error .play-button) {
        display: none;
    }
</style>
