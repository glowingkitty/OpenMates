<script lang="ts">
    import ChatMessage from './ChatMessage.svelte';
    import EventAppCard from './cards/EventAppCard.svelte';
    import HealthAppCard from './cards/HealthAppCard.svelte';
    import ProcessingDetails from './ProcessingDetails.svelte';
    import { onMount, onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import { getLocaleFromNavigator, waitLocale } from 'svelte-i18n';

    // Add at the top of the script section
    type ChatExample = {
        app: string;
        sequence: MessageSequence[];
    };

    // Update type definition
    type MessageSequence = {
        type: string;
        text?: string;
        waitTime?: number;
        appNames?: string[];
        focusName?: string;
        focusIcon?: string;
        mateName?: string;
        in_progress?: boolean;
        appCards?: any[];
    };

    // Add loading state
    let isTranslationsLoaded = false;
    
    // Initialize empty chat examples array
    let chatExamples: ChatExample[] = [];

    // Create reactive statement for chat examples
    $: if ($_) {
        chatExamples = [
            // Career advice conversation with loaded preferences
            {
                app: 'ai',
                sequence: [
                    {
                        type: 'user',
                        text: $_('chat_examples.career.user_question.text'),
                        waitTime: 2500
                    },
                    {
                        type: 'started_focus',
                        appNames: ['Jobs'],
                        focusName: $_('chat_examples.processing.career_insights.text'),
                        focusIcon: 'insights',
                        waitTime: 1500
                    },
                    {
                        type: 'loaded_preferences',
                        appNames: ['Jobs'],
                        waitTime: 1500
                    },
                    {
                        type: 'mate',
                        mateName: 'Burton',
                        text: $_('chat_examples.career.mate_response.text'),
                        waitTime: 3000
                    }
                ]
            },
            // Events conversation
            {
                app: 'events',
                sequence: [
                    {
                        type: 'user',
                        text: $_('chat_examples.events.user_question.text'),
                        waitTime: 2500
                    },
                    {
                        type: "using_apps",
                        appNames: ["events"],
                        in_progress: false,
                        waitTime: 1500
                    },
                    {
                        type: 'mate',
                        mateName: 'Lisa',
                        text: $_('chat_examples.events.mate_response.text'),
                        waitTime: 3000,
                        appCards: [
                            {
                                component: EventAppCard,
                                props: {
                                    size: 'small',
                                    date: $_('chat_examples.events.calendar.today.text'),
                                    time: '18:30',
                                    eventName: $_('chat_examples.events.events.book_club.text'),
                                    participants: 12,
                                    imageUrl: '@openmates/shared/static/images/examples/group1.jpg'
                                }
                            },
                            {
                                component: EventAppCard,
                                props: {
                                    size: 'small',
                                    date: $_('chat_examples.events.calendar.dec_15.text'),
                                    time: '19:00',
                                    eventName: $_('chat_examples.events.events.tech_talk.text'),
                                    participants: 76,
                                    imageUrl: '@openmates/shared/static/images/examples/group2.jpg'
                                }
                            },
                            {
                                component: EventAppCard,
                                props: {
                                    size: 'small',
                                    date: $_('chat_examples.events.calendar.dec_16.text'),
                                    time: '18:00',
                                    eventName: $_('chat_examples.events.events.workshop.text'),
                                    participants: 13,
                                    imageUrl: '@openmates/shared/static/images/examples/group2.jpg'
                                }
                            }
                        ]
                    }
                ]
            },
            // Health conversation
            {
                app: 'health',
                sequence: [
                    {
                        type: 'user',
                        text: $_('chat_examples.health.user_question.text'),
                        waitTime: 2500
                    },
                    {
                        type: 'mate',
                        mateName: 'Melvin',
                        text: $_('chat_examples.health.mate_initial.text'),
                        waitTime: 2500
                    },
                    {
                        type: "using_apps",
                        appNames: ["calendar", "health"],
                        in_progress: false,
                        waitTime: 2500
                    },
                    {
                        type: 'mate',
                        mateName: 'Melvin',
                        text: $_('chat_examples.health.mate_response.text'),
                        waitTime: 3000,
                        appCards: [
                                {
                                    component: HealthAppCard,
                                    props: {
                                        size: 'large',
                                        date: $_('chat_examples.health.calendar.wed.text'),
                                        start: '9:00',
                                        end: '10:00',
                                        doctorName: $_('chat_examples.health.doctors.van_hausen.text'),
                                        specialty: $_('chat_examples.health.doctors.specialty.text'),
                                        rating: 4.2,
                                        ratingCount: 85,
                                        showCalendar: true,
                                        existingAppointments: [
                                            {start: '13:00', end: '15:00'}
                                        ]
                                    }
                                },
                                {
                                    component: HealthAppCard,
                                    props: {
                                        size: 'large',
                                        date: $_('chat_examples.health.calendar.thu.text'),
                                        start: '11:30',
                                        end: '12:30',
                                        doctorName: $_('chat_examples.health.doctors.williams.text'),
                                        specialty: $_('chat_examples.health.doctors.specialty.text'),
                                        rating: 4.8,
                                        ratingCount: 124,
                                        showCalendar: true,
                                        existingAppointments: [
                                            {start: '14:00', end: '16:00'}
                                        ]
                                    }
                                },
                                {
                                    component: HealthAppCard,
                                    props: {
                                        size: 'large',
                                        date: $_('chat_examples.health.calendar.fri.text'),
                                        start: '15:00',
                                        end: '16:00',
                                        doctorName: $_('chat_examples.health.doctors.chen.text'),
                                        specialty: $_('chat_examples.health.doctors.specialty.text'),
                                        rating: 4.6,
                                        ratingCount: 93,
                                        showCalendar: true,
                                        existingAppointments: [
                                            {start: '10:00', end: '12:00'}
                                        ]
                                    }
                                }
                            ]
                    }
                ]
            }
            // Add more conversations as needed
        ];
        isTranslationsLoaded = true;
    }

    let currentExampleIndex = 0;
    let visibleMessages: Array<MessageSequence & {animated?: boolean}> = [];
    let currentSequenceIndex = 0;
    
    // Add new variable to track processing state
    let currentProcessingMessage: any = null;

    // Add export for currentApp
    export let currentApp = '';

    let animationInProgress = false;
    let currentAnimationId = 0;

    let cleanup = () => {};

    // Add at the top with other types
    type MessagePart = {
        type: 'text' | 'app-cards';
        content: string | any[];  // or be more specific with AppCardData[] if available
    };

    // Add new prop
    export let singleExample = false;

    // Add new prop for highlight context
    export let inHighlight = false;

    let observer: IntersectionObserver;
    let containerElement: HTMLElement;
    let isVisible = false;
    let isPaused = false;
    let animationStarted = false;
    let lastAnimationTime = 0;

    // Add a new variable to track completion
    let isCompleted = false;

    // Add constant for message spacing
    const MESSAGE_SPACING = 20; // Standard spacing between messages

    // Add at the top of the script section
    let instanceId = crypto.randomUUID();
    let messageHeights: number[] = [];

    // Calculate containerMarginTop reactively
    $: containerMarginTop = (() => {
        // Calculate total height including spacing between messages
        const totalHeight = messageHeights.reduce((sum, height, index) => {
            let heightWithSpacing = height;
            if (index < messageHeights.length - 1) {
                heightWithSpacing += MESSAGE_SPACING;
            }
            return sum + heightWithSpacing;
        }, 0);

        // Calculate the distance to move up (negative moves up)
        // We want to keep the last message at the bottom
        return messageHeights.length > 1 ? totalHeight - messageHeights[messageHeights.length - 1] : 0;
    })();

    // Clean up instance data on component destroy
    onDestroy(() => {
        messageHeights = [];
    });

    // Add helper function to check for duplicates
    function isDuplicateMessage(message: MessageSequence, messages: Array<MessageSequence & {animated?: boolean}>): boolean {
        return messages.some(existing => 
            existing.type === message.type && 
            existing.text === message.text &&
            existing.mateName === message.mateName
        );
    }

    // Modify the addMessageWithAnimation function to prevent resetting transform
    async function addMessageWithAnimation(message: MessageSequence) {
        if (!isDuplicateMessage(message, visibleMessages)) {
            const messageWithAnimation = { ...message, animated: false };
            
            // Create new array without mutating state directly
            const newVisibleMessages = [...visibleMessages, messageWithAnimation];
            visibleMessages = newVisibleMessages;

            // Wait for DOM update
            await waitForNextFrame();

            // Get height of the newly added message
            const messageElements = document.querySelectorAll(`.animated-chat-container[data-instance="${instanceId}"] > div`);
            const newMessageElement = messageElements[messageElements.length - 1];
            if (newMessageElement) {
                const height = (newMessageElement as HTMLElement).offsetHeight;
                messageHeights = [...messageHeights, height];
            }

            // Set animated flag without resetting the transform
            messageWithAnimation.animated = true;
            visibleMessages = [...newVisibleMessages];
        }
    }

    // Modify the animateMessages function to prevent resetting transform
    async function animateMessages() {
        const thisAnimationId = ++currentAnimationId;
        if (animationInProgress) {
            return;
        }

        try {
            animationInProgress = true;

            // Only reset messages when starting new example and not in single example mode
            if (!singleExample && currentSequenceIndex === 0) {
                visibleMessages = [];
                messageHeights = [];  // Reset heights only when resetting messages
            }

            let example = singleExample ?
                chatExamples.find(ex => ex.app === currentApp) :
                chatExamples[currentExampleIndex];

            if (!example) return;

            // Update currentApp for both header and highlight cases
            if (!singleExample) {
                currentApp = example.app;
            }

            // Continue from where we left off if paused
            for (let i = currentSequenceIndex; i < example.sequence.length; i++) {
                if (!isVisible || isPaused) {
                    currentSequenceIndex = i;
                    return;
                }

                const message = example.sequence[i];

                if (thisAnimationId !== currentAnimationId) return;

                if (message.type === 'using_apps') {
                    if (!currentProcessingMessage) {
                        currentProcessingMessage = { ...message, animated: true };
                        await addMessageWithAnimation(currentProcessingMessage);
                    } else {
                        Object.assign(currentProcessingMessage, {
                            in_progress: message.in_progress,
                            appNames: message.appNames
                        });
                        visibleMessages = [...visibleMessages];
                    }
                } else {
                    await addMessageWithAnimation(message);
                }

                // Use message-specific wait time instead of fixed delay
                const delay = message.waitTime || 2000; // Default to 2 seconds if no waitTime specified
                await new Promise(resolve => setTimeout(resolve, delay));

                // Update sequence index after each message
                currentSequenceIndex = i + 1;
            }

            if (thisAnimationId !== currentAnimationId) return;

            // Mark as completed after final delay
            await new Promise(resolve => setTimeout(resolve, 5000));

            resetAppIcon(example.app);

            // Only clear currentApp if we're cycling through examples
            if (!singleExample) {
                currentApp = '';
            }

            if (inHighlight) {
                isCompleted = true;  // Mark as completed for highlights
            } else if (!singleExample) {
                // When cycling to next example, only reset sequence index and messages
                // but maintain the transform
                currentExampleIndex = (currentExampleIndex + 1) % chatExamples.length;
                currentSequenceIndex = 0;
                visibleMessages = [];
                isPaused = false;
                if (isVisible) {
                    requestAnimationFrame(() => animateMessages());
                }
            }

        } finally {
            if (thisAnimationId === currentAnimationId) {
                animationInProgress = false;
            }
        }
    }

    // Function to highlight app icon
    function highlightAppIcon(appName: string) {
        const targetIcon = document.querySelector(`.icon-wrapper[data-app="${appName}"]`);
        if (targetIcon) {
            // Determine if the icon is on the left or right side
            const isLeftSide = targetIcon.closest('.icon-grid.left') !== null;

            // Add the appropriate slide class
            if (isLeftSide) {
                targetIcon.classList.add('slide-right');
            } else {
                targetIcon.classList.add('slide-left');
            }
        }
    }

    // Reset icon
    function resetAppIcon(appName: string) {
        const targetIcon = document.querySelector(`.icon-wrapper[data-app="${appName}"]`);
        if (targetIcon) {
            // Remove both slide classes
            targetIcon.classList.remove('slide-right', 'slide-left');
        }
    }

    // Added helper function for repeated requestAnimationFrame calls and made code more readable
    function waitForNextFrame() {
        // This utility function centralizes our requestAnimationFrame usage
        return new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    }

    onMount(() => {
        // Just keep the intersection observer setup
        initIntersectionObserver();

        return () => {
            observer?.disconnect();
            currentAnimationId++;
            cleanup();
        };
    });

    // Demonstration of new helper for highlight animations (instead of inlining logic)
    function manageHighlightAnimation() {
        if (!animationStarted) {
            animationStarted = true;
            isCompleted = false;
            currentSequenceIndex = 0;
            visibleMessages = [];
            isPaused = false;
            requestAnimationFrame(() => animateMessages());
        } else if (isPaused && !isCompleted) {
            // Resume from current position if paused and not completed
            isPaused = false;
            requestAnimationFrame(() => animateMessages());
        }
    }

    // Similarly, extract the header animation handling
    function manageHeaderAnimation() {
        if (isPaused || (!animationInProgress && !singleExample)) {
            requestAnimationFrame(() => animateMessages());
        }
    }

    // Consolidate IntersectionObserver setup into a dedicated function for clarity
    function initIntersectionObserver() {
        observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    const wasVisible = isVisible;
                    isVisible = entry.isIntersecting;

                    // Only start or resume animations when becoming visible
                    if (!wasVisible && isVisible) {
                        if (inHighlight) {
                            // For highlights - single example animation
                            if (!animationStarted) {
                                animationStarted = true;
                                isCompleted = false;
                                currentSequenceIndex = 0;
                                visibleMessages = [];
                                isPaused = false;
                                requestAnimationFrame(() => animateMessages());
                            } else if (isPaused && !isCompleted) {
                                isPaused = false;
                                requestAnimationFrame(() => animateMessages());
                            }
                        } else {
                            // For header - cycling through all examples
                            isPaused = false;
                            if (!animationInProgress && !singleExample) {
                                // Reset messages when starting a new cycle
                                visibleMessages = [];
                                currentSequenceIndex = 0;
                                requestAnimationFrame(() => animateMessages());
                            }
                        }
                    } else if (wasVisible && !isVisible) {
                        currentAnimationId++;
                        if (!isCompleted) {
                            isPaused = true;
                        }
                        animationInProgress = false;
                    }
                });
            },
            inHighlight
                ? { threshold: [0.6], rootMargin: '-10% 0px' }
                : { threshold: [0.5], rootMargin: '0px' }
        );
        if (containerElement) {
            observer.observe(containerElement);
        }
    }
</script>

<!-- Only show content when translations are loaded -->
{#if isTranslationsLoaded}
    <div
        class="chat-examples-container"
        class:in-highlight={inHighlight}
        bind:this={containerElement}
    >
        <div class="chat-content" class:in-highlight={inHighlight}>
            <div 
                class="animated-chat-container"
                style="--container-margin-top: {containerMarginTop}px;"
                data-instance={instanceId}
            >
                {#each visibleMessages as message (message.type === 'using_apps' ? 'processing' : message)}
                    <div>
                        {#if message.type === 'using_apps' || message.type === 'started_focus' || message.type === 'loaded_preferences'}
                            <ProcessingDetails
                                type={message.type}
                                in_progress={message.in_progress}
                                appNames={message.appNames}
                                focusName={message.focusName}
                                focusIcon={message.focusIcon}
                            />
                        {:else}
                            <ChatMessage
                                role={message.type === 'user' ? 'user' : message.mateName?.toLowerCase() ?? 'mate'}
                                messageParts={message.appCards && message.text ? [
                                    { type: 'text', content: message.text },
                                    { type: 'app-cards', content: message.appCards }
                                ] : undefined}
                                animated={message.animated}
                                defaultHidden={true}
                            >
                                {message.text}
                            </ChatMessage>
                        {/if}
                    </div>
                {/each}
            </div>
        </div>
    </div>
{/if}

<style>
    .chat-examples-container {
        position: relative;
        height: 300px;
        width: 540px;
        margin: 0 auto;
        user-select: none; /* Make text not selectable */
    }

    /* Add media query for smaller screens */
    @media (max-width: 560px) {
        .chat-examples-container {
            width: 100%;
        }
    }

    /* Adjust container when used in highlights */
    .chat-examples-container.in-highlight {
        height: 100%;
        width: 100%;
    }

    .chat-content {
        position: relative;
        height: 100%;
        overflow: hidden;
        /* Replace the old gradient mask with a more pronounced one */
        -webkit-mask-image: linear-gradient(
            to bottom,
            transparent 0%,
            black 10%,
            black 90%,
            transparent 100%
        );
        mask-image: linear-gradient(
            to bottom,
            transparent 0%,
            black 10%,
            black 90%,
            transparent 100%
        );
    }

    .animated-chat-container {
        width: 100%;
        margin: 0 auto;
        padding: 1rem;
        user-select: none;
        padding-top: 15px;
        padding-bottom: 15px;
        will-change: transform;
        display: flex;
        flex-direction: column;
        gap: 20px;
        transform: translateY(calc(-1 * var(--container-margin-top)));
        transition: transform 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }

    @media (max-width: 560px) {
        .animated-chat-container {
            max-width: 320px;
        }
    }

    :global(.app-title svg) {
        width: 67.98px !important;
        height: 67.98px !important;
        min-width: 67.98px !important;
        min-height: 67.98px !important;
    }

    /* Disable all hover effects and cursor changes for elements in the animated chat */
    :global(.chat-examples-container .app-card) {
        pointer-events: none !important;
        cursor: default !important;
        transition: none !important;
        transform: none !important;
    }

    :global(.chat-examples-container .app-card:hover) {
        transform: none !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
    }

    /* Add these new rules to disable hover effects and cursor changes */
    :global(.chat-examples-container .processing-details),
    :global(.chat-examples-container .processing-details *) {
        pointer-events: none !important;
        cursor: default !important;
        transition: none !important;
    }

    :global(.chat-examples-container .processing-details:hover) {
        transform: none !important;
        filter: none !important;
    }

    /* Ensure all text within the container is not selectable */
    :global(.chat-examples-container *) {
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        user-select: none;
        pointer-events: none;
        cursor: default;
    }
</style>