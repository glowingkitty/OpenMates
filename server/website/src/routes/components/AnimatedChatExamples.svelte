<script lang="ts">
    import ChatMessage from './ChatMessage.svelte';
    import EventAppCard from './cards/EventAppCard.svelte';
    import HealthAppCard from './cards/HealthAppCard.svelte';
    import ProcessingDetails from './ProcessingDetails.svelte';
    import { onMount, onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';

    // Add at the top of the script section
    type ChatExample = {
        app: string;
        sequence: MessageSequence[];
    };

    // Update the chatExamples declaration
    const chatExamples: ChatExample[] = [
        // Career advice conversation with loaded preferences
        {
            app: 'ai',
            sequence: [
                {
                    type: 'user',
                    text: 'I am unhappy in my current job. Any ideas in what direction I could go instead?',
                    waitTime: 2000
                },
                {
                    type: 'started_focus',
                    appNames: ['Jobs'],
                    focusName: 'Career insights',
                    focusIcon: 'insights',
                    waitTime: 500
                },
                {
                    type: 'loaded_preferences',
                    appNames: ['Jobs'],
                    waitTime: 500
                },
                {
                    type: 'mate',
                    mateName: 'Burton',
                    text: 'Of course! Since you mentioned that you have a background in marketing and enjoy storytelling, we could look for roles that leverage those skills.\n\nTo get a better sense of direction, could you tell me:\n1. What aspects of your previous jobs did you find most fulfilling?',
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
                    text: 'What events are happening the coming days?',
                    waitTime: 2000
                },
                {
                    type: "using_apps",
                    appNames: ["events"],
                    in_progress: false,
                    waitTime: 500
                },
                {
                    type: 'mate',
                    mateName: 'Lisa',
                    text: 'There are some exciting events going on the coming days! Both to help you learn for a better career and to socialize more.',
                    waitTime: 3000,
                    appCards: [
                        {
                            component: EventAppCard,
                            props: {
                                size: 'small',
                                date: 'Today',
                                time: '18:30',
                                eventName: "Book Lovers' Social: An Evening of Reading and Discussion",
                                participants: 12,
                                imageUrl: '/images/examples/group1.jpg'
                            }
                        },
                        {
                            component: EventAppCard,
                            props: {
                                size: 'small',
                                date: 'Dec 15',
                                time: '19:00',
                                eventName: 'TechTalk: AI in Everyday Business',
                                participants: 76,
                                imageUrl: '/images/examples/group2.jpg'
                            }
                        },
                        {
                            component: EventAppCard,
                            props: {
                                size: 'small',
                                date: 'Dec 16',
                                time: '18:00',
                                eventName: 'Workshop: Building AI-Powered Applications',
                                participants: 13,
                                imageUrl: '/images/examples/group2.jpg'
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
                    text: "What is the next available cardiologist appointment, that doesn't collide with my calendar?",
                    waitTime: 2500
                },
                {
                    type: 'mate',
                    mateName: 'Melvin',
                    text: 'Let me quickly check your calendar and search for available doctor appointments. I will come back to you in a minute.',
                    waitTime: 1500
                },
                {
                    type: "using_apps",
                    appNames: ["calendar", "health"],
                    in_progress: false,
                    waitTime: 500
                },
                {
                    type: 'mate',
                    mateName: 'Melvin',
                    text: "The best appointment I could find is tomorrow at 9:00. Doesn't collide with your product launch meeting later that day.",
                    waitTime: 3000,
                    appCards: [
                        {
                            component: HealthAppCard,
                            props: {
                                size: 'large',
                                date: 'Wed, Dec 12',
                                start: '9:00',
                                end: '10:00',
                                doctorName: 'Dr. Van Hausen',
                                specialty: 'Cardiologist',
                                rating: 4.2,
                                ratingCount: 85,
                                showCalendar: true,
                                existingAppointments: [
                                    {start: '13:00', end: '15:00'}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        // Add more conversations as needed
    ];

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

    // Define a type for the message sequences
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

    // Add at the top with other types
    type MessagePart = {
        type: 'text' | 'app-cards';
        content: string | any[];  // or be more specific with AppCardData[] if available
    };

    // Modified function to animate messages
    async function animateMessages() {
        // Cancel any ongoing animation
        const thisAnimationId = ++currentAnimationId;
        if (animationInProgress) {
            return;
        }

        try {
            animationInProgress = true;
            const currentExample = chatExamples[currentExampleIndex];
            currentApp = currentExample.app;

            visibleMessages = [];
            currentProcessingMessage = null;
            currentSequenceIndex = 0;

            // Reset icons with proper error handling
            try {
                const icons = document.querySelectorAll('.icon-wrapper');
                icons.forEach(icon => icon.classList.remove('slide-right', 'slide-left'));

                if (currentExample.app) {
                    highlightAppIcon(currentExample.app);
                }
            } catch (error) {
                console.error('Error handling icons:', error);
            }

            // Animate messages with processing states
            for (let i = 0; i < currentExample.sequence.length; i++) {
                const message = currentExample.sequence[i];

                if (thisAnimationId !== currentAnimationId) return;

                if (message.type === 'using_apps') {
                    // Update or create processing message
                    if (!currentProcessingMessage) {
                        currentProcessingMessage = { ...message, animated: true };
                        visibleMessages = [...visibleMessages, currentProcessingMessage];
                    } else {
                        // Update existing processing message
                        Object.assign(currentProcessingMessage, {
                            in_progress: message.in_progress,
                            appNames: message.appNames
                        });
                        visibleMessages = [...visibleMessages];
                    }
                } else if (message.type === 'started_focus' || message.type === 'loaded_preferences') {
                    // Add new processing details for other types
                    const messageWithAnimation = { ...message, animated: false };
                    visibleMessages = [...visibleMessages, messageWithAnimation];

                    await new Promise(resolve => requestAnimationFrame(resolve));
                    await new Promise(resolve => requestAnimationFrame(resolve));

                    if (thisAnimationId !== currentAnimationId) return;

                    messageWithAnimation.animated = true;
                    visibleMessages = [...visibleMessages];
                } else {
                    // Handle regular messages (user/mate)
                    const messageWithAnimation = { ...message, animated: false };
                    visibleMessages = [...visibleMessages, messageWithAnimation];

                    await new Promise(resolve => requestAnimationFrame(resolve));
                    await new Promise(resolve => requestAnimationFrame(resolve));

                    if (thisAnimationId !== currentAnimationId) return;

                    messageWithAnimation.animated = true;
                    visibleMessages = [...visibleMessages];
                }

                // Use waitTime from sequence or calculate default
                const delay = message.waitTime ?? (message.text ? 
                    Math.min(2000 + (message.text.length * 20), 4000) : 
                    (message.type === 'using_apps' ? (message.in_progress ? 1000 : 500) : 2000)
                );

                await new Promise(resolve => setTimeout(resolve, delay));
            }

            if (thisAnimationId !== currentAnimationId) return;

            await new Promise(resolve => setTimeout(resolve, 5000));

            resetAppIcon(currentExample.app);
            currentApp = '';
            currentExampleIndex = (currentExampleIndex + 1) % chatExamples.length;

            // Recursively call with a frame delay to prevent stack overflow
            requestAnimationFrame(() => animateMessages());

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

    onMount(() => {
        animateMessages();
        return () => {
            currentAnimationId++; // Cancel any running animation
            cleanup();
        };
    });

    onDestroy(() => {
        cleanup();
        currentAnimationId++; // Ensure no animations continue
    });
</script>

<div class="chat-examples-container">
    <div class="chat-content">
        <div class="gradient-overlay top"></div>
        <div class="animated-chat-container">
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
        <div class="gradient-overlay bottom"></div>
    </div>
</div>

<style>
    .chat-examples-container {
        position: relative;
        height: 300px;
        width: 540px;
        margin: 0 auto;
    }

    .chat-content {
        position: relative;
        height: 100%;
        overflow: hidden;
        -webkit-mask-image: linear-gradient(to bottom, transparent, black 15%, black 85%, transparent);
        mask-image: linear-gradient(to bottom, transparent, black 15%, black 85%, transparent);
    }

    .gradient-overlay {
        display: none;
    }

    .animated-chat-container {
        width: 100%;
        margin: 0 auto;
        padding: 1rem;
        user-select: none;
        padding-top: 15px;
        padding-bottom: 15px;
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
</style>