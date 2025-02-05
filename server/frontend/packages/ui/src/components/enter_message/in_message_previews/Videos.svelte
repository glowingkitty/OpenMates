<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onDestroy } from 'svelte';
    import { _ } from 'svelte-i18n';
    
    export let src: string;
    export let filename: string | null = null;
    export let id: string;
    export let duration: string; // Format: "MM:SS"
    export let isRecording: boolean = false;
    export let thumbnailUrl: string | undefined = undefined;
    export let isYouTube: boolean = false;
    export let videoId: string | undefined = undefined;

    let videoElement: HTMLVideoElement;
    let isPlaying = false;
    let currentTime = '00:00';
    let progress = 0;
    let thumbnailLoaded = false;
    let videoHeight = 0;
    let showCopied = false;

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

    // Add thumbnail quality fallback chain
    const THUMBNAIL_QUALITIES = [
        'maxresdefault.jpg',
        'hqdefault.jpg',
        'mqdefault.jpg',
        'sddefault.jpg',
        'default.jpg'
    ];

    let currentThumbnailQualityIndex = 0;

    function tryNextThumbnailQuality(img: HTMLImageElement) {
        currentThumbnailQualityIndex++;
        if (currentThumbnailQualityIndex < THUMBNAIL_QUALITIES.length && videoId) {
            img.src = `https://i.ytimg.com/vi/${videoId}/${THUMBNAIL_QUALITIES[currentThumbnailQualityIndex]}`;
        }
    }

    // Create an event handler for image error events
    function handleThumbnailError(e: Event) {
        // Use a type assertion here to get the HTMLImageElement from the event target
        const img = e.target as HTMLImageElement;
        logger.debug('Thumbnail error encountered, trying next quality');
        tryNextThumbnailQuality(img);
    }

    // Update the isVideoPlayable function to be less aggressive
    async function isVideoPlayable(videoElement: HTMLVideoElement): Promise<boolean> {
        try {
            // Only check if metadata can be loaded
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
            
            // Remove the play/pause check since it can interfere with other media
            return true;
        } catch (error) {
            logger.debug('Video playability check failed:', error);
            return false;
        }
    }

    // Update initVideo function to handle YouTube videos properly
    async function initVideo() {
        if (isYouTube) {
            // For YouTube videos, we'll set some default values and skip video element initialization
            thumbnailLoaded = true;
            if (!duration || duration === '00:00') {
                duration = '--:--'; // Placeholder until we can fetch duration
            }
            return;
        }

        if (!src) {
            logger.debug('No video source provided, skipping initialization');
            return;
        }

        logger.debug(`Initializing video player for ${id}`, {
            initialDuration: duration,
            src,
            isRecording
        });

        try {
            // Create video element only if it doesn't exist
            if (!videoElement) {
                videoElement = document.createElement('video');
                videoElement.src = src;
                videoElement.preload = 'metadata';
            }

            // Add timeupdate event listener with null check
            videoElement.addEventListener('timeupdate', () => {
                if (!videoElement) return;
                
                const videoDuration = videoElement.duration;
                if (isFinite(videoDuration) && videoDuration > 0) {
                    currentTime = formatTime(videoElement.currentTime);
                    progress = (videoElement.currentTime / videoDuration) * 100;
                    logger.debug('Video progress:', { currentTime, progress });
                }
            });

            // Determine timeout based on file type and size
            const isMovFile = filename?.toLowerCase().endsWith('.mov');
            const isLargeFile = src.includes('blob') && src.length > 1000000; // Rough estimate for large files
            const timeoutDuration = isMovFile || isLargeFile ? 30000 : 15000; // 30 seconds for .mov/large files, 15 for others

            // Create a promise that resolves when metadata is loaded
            const metadataPromise = new Promise<void>((resolve, reject) => {
                let metadataLoaded = false;
                let retryCount = 0;
                const maxRetries = 3;

                const tryLoadMetadata = () => {
                    if (!videoElement) return;
                    
                    if (isFinite(videoElement.duration) && videoElement.duration > 0) {
                        duration = formatTime(videoElement.duration);
                        logger.debug('Duration found:', duration);
                        metadataLoaded = true;
                        resolve();
                        return true;
                    }
                    return false;
                };

                const retryLoadMetadata = () => {
                    if (retryCount < maxRetries && !metadataLoaded) {
                        retryCount++;
                        logger.debug(`Retrying metadata load, attempt ${retryCount}`);
                        videoElement.load();
                    } else if (!metadataLoaded) {
                        reject(new Error('Failed to load video metadata after retries'));
                    }
                };

                // Event listeners for metadata loading
                const events = ['loadedmetadata', 'durationchange', 'loadeddata'];
                events.forEach(event => {
                    videoElement.addEventListener(event, () => {
                        if (!metadataLoaded && tryLoadMetadata()) {
                            // Update video height based on aspect ratio
                            videoHeight = (videoElement.videoHeight / videoElement.videoWidth) * 300;
                            thumbnailLoaded = true;
                        }
                    });
                });

                // Handle loading errors
                videoElement.addEventListener('error', (e) => {
                    const error = videoElement.error;
                    logger.debug('Video loading error:', {
                        code: error?.code,
                        message: error?.message,
                        event: e
                    });
                    retryLoadMetadata();
                });

                // Initial load attempt
                if (!tryLoadMetadata()) {
                    videoElement.load();
                }
            });

            // Wait for metadata with timeout and fallback handling
            try {
                await Promise.race([
                    metadataPromise,
                    new Promise((_, reject) => {
                        setTimeout(() => {
                            if (!videoElement || !isFinite(videoElement.duration) || videoElement.duration === 0) {
                                reject(new Error(`Video metadata timeout after ${timeoutDuration}ms`));
                            }
                        }, timeoutDuration);
                    })
                ]);
            } catch (error) {
                logger.debug('Error loading video metadata:', error);
                // Fallback: Try to get duration from the filename or use default
                if (!duration || duration === '00:00') {
                    // Look for duration pattern in filename (e.g., "video_2m30s.mp4")
                    const durationMatch = filename?.match(/(\d+)m(\d+)s/);
                    if (durationMatch) {
                        const [_, minutes, seconds] = durationMatch;
                        duration = `${minutes.padStart(2, '0')}:${seconds.padStart(2, '0')}`;
                    } else {
                        duration = '00:00';
                    }
                }
            }

            // Update ended event handler
            videoElement.addEventListener('ended', () => {
                isPlaying = false;
                progress = 0;
                currentTime = '00:00';
                videoElement.currentTime = 0;
                logger.debug('Video playback ended, resetting state');
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
        } catch (error) {
            logger.debug('Error initializing video:', error);
            duration = duration || '00:00';
            progress = 0;
            currentTime = '00:00';
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

    // Update togglePlay function
    async function togglePlay(e: MouseEvent) {
        e.stopPropagation();
        
        if (isYouTube && videoId) {
            // Open YouTube video in new tab with timestamp if playing
            const timestamp = videoElement?.currentTime ? `&t=${Math.floor(videoElement.currentTime)}` : '';
            window.open(`https://www.youtube.com/watch?v=${videoId}${timestamp}`, '_blank');
            return;
        }

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
        } catch (err) {
            logger.debug('Error toggling video playback:', err);
        }
    }

    // Add an explicit ended event handler for the video element
    function handleVideoEnded() {
        isPlaying = false;
        progress = 0;
        currentTime = '00:00';
        if (videoElement) {
            videoElement.currentTime = 0;
        }
        logger.debug('Video ended event handled');
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

    // Add this near the top of the script section
    $: if (isYouTube && videoId && (!duration || duration === '00:00')) {
        duration = '--:--';
    }

    // Add this URL formatting helper function near the top of the script section
    function formatUrlParts(url: string) {
        try {
            const urlObj = new URL(url);
            const parts = {
                subdomain: '',
                domain: '',
                path: ''
            };

            const hostParts = urlObj.hostname.split('.');
            if (hostParts.length > 2) {
                parts.subdomain = hostParts[0] + '.';
                parts.domain = hostParts.slice(1).join('.');
            } else {
                parts.domain = urlObj.hostname;
            }

            const fullPath = urlObj.pathname + urlObj.search + urlObj.hash;
            parts.path = fullPath === '/' ? '' : fullPath;

            return parts;
        } catch (error) {
            logger.debug('Error formatting URL:', error);
            return {
                subdomain: '',
                domain: filename || '',
                path: ''
            };
        }
    }

    // Add this computed property
    $: urlParts = isYouTube && filename ? formatUrlParts(filename) : null;
</script>

<InlinePreviewBase 
    {id} 
    type={isRecording ? 'video_recording' : 'video'}
    {src} 
    {filename} 
    height="200px"
    customClass={`${isPlaying ? 'playing' : ''} ${videoElement?.error ? 'error' : ''} ${isYouTube ? 'youtube' : ''}`}
>
    <div class="video-container">
        {#if isYouTube}
            <div class="youtube-preview">
                <img 
                    src={thumbnailUrl} 
                    alt="YouTube thumbnail" 
                    class="thumbnail"
                    on:error={handleThumbnailError}
                />
            </div>
        {:else}
            {#if videoElement}
                <video 
                    class="video-element" 
                    src={src}
                    bind:this={videoElement}
                    on:timeupdate={() => {
                        if (videoElement) {
                            const videoDuration = videoElement.duration;
                            if (isFinite(videoDuration) && videoDuration > 0) {
                                currentTime = formatTime(videoElement.currentTime);
                                progress = (videoElement.currentTime / videoDuration) * 100;
                            }
                        }
                    }}
                    on:ended={handleVideoEnded}
                    on:error={() => logger.debug('Video element error event triggered')}
                >
                    <track kind="captions" />
                </video>
            {/if}
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
                {#if filename && !isRecording}
                    {#if isYouTube && urlParts}
                        <div class="url">
                            <div class="domain-line">
                                <span class="subdomain">{urlParts.subdomain}</span>
                                <span class="main-domain">{urlParts.domain}</span>
                            </div>
                            {#if urlParts.path}
                                <span class="path">{urlParts.path}</span>
                            {/if}
                        </div>
                        <div class="copied-message">
                            {$_('enter_message.press_and_hold_menu.copied_to_clipboard.text')}
                        </div>
                    {:else}
                        <span class="filename">{filename}</span>
                    {/if}
                {/if}
                <span class="time-info">
                    {#if !isYouTube}
                        <span class="duration">{duration}</span>
                    {/if}
                </span>
            </div>
        </div>

        <!-- Play button outside info-bar -->
        {#if !isYouTube}
            <button 
                class="play-button clickable-icon {isPlaying ? 'icon_pause' : 'icon_play'}"
                aria-label={isPlaying ? 'Pause' : 'Play'}
                on:click={togglePlay}
            ></button>
        {/if}
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

    /* Update YouTube preview styles */
    .youtube-preview {
        position: relative;
        width: 100%;
        height: 200px; /* Match the container height */
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .thumbnail {
        width: 100%;
        height: 100%;
        object-fit: cover;
        position: absolute;
        top: 0;
        left: 0;
    }

    .url {
        display: flex;
        flex-direction: column;
        line-height: 1.3;
        font-size: 14px;
        width: 100%;
        word-break: break-word;
        max-height: 2.6em;
        overflow: hidden;
    }

    .domain-line {
        display: flex;
        flex-direction: row;
        align-items: baseline;
    }

    .subdomain {
        color: var(--color-font-tertiary);
    }

    .main-domain {
        color: var(--color-font-primary);
    }

    .path {
        color: var(--color-font-tertiary);
        display: block;
        text-overflow: ellipsis;
        overflow: hidden;
        white-space: nowrap;
    }

    /* Add near other styles */
    .copied-message {
        position: absolute;
        top: 50%;
        left: 0;
        width: 100%;
        transform: translateY(-50%);
        text-align: center;
        opacity: 0;
        transition: opacity 0.2s ease-in-out;
    }

    :global(.preview-container.show-copied .url) {
        opacity: 0;
    }

    :global(.preview-container.show-copied .copied-message) {
        opacity: 1;
    }
</style>
