<script lang="ts">
    import ChatMessage from './ChatMessage.svelte';
    import EventAppCard from './cards/EventAppCard.svelte';
    import HealthAppCard from './cards/HealthAppCard.svelte';
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';

    // Import example chat content from the main page
    const chatExamples = [
        // Events conversation
        {
            sequence: [
                {
                    type: 'user',
                    text: 'What events are happening the coming days?',
                    highlightApp: 'events'
                },
                {
                    type: 'mate',
                    mateName: 'Lisa',
                    text: 'There are some exciting events going on the coming days! Both to help you learn for a better career and to socialize more.',
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
                        }
                    ]
                }
            ]
        },
        // Health conversation
        {
            sequence: [
                {
                    type: 'user',
                    text: "What is the next available cardiologist appointment, that doesn't collide with my calendar?",
                    highlightApp: 'health'
                },
                {
                    type: 'mate',
                    mateName: 'Melvin',
                    text: 'Let me quickly check your calendar and search for available doctor appointments. I will come back to you in a minute.'
                },
                {
                    type: 'mate',
                    mateName: 'Melvin',
                    text: "The best appointment I could find is tomorrow at 9:00. Doesn't collide with your product launch meeting later that day.",
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
    let visibleMessages: any[] = [];
    let currentSequenceIndex = 0;

    // Function to animate messages
    async function animateMessages() {
        const currentExample = chatExamples[currentExampleIndex];

        // Reset messages when starting new example
        visibleMessages = [];
        currentSequenceIndex = 0;

        // Animate each message in sequence
        for (const message of currentExample.sequence) {
            visibleMessages = [...visibleMessages, message];

            // Highlight corresponding app icon
            if (message.highlightApp) {
                highlightAppIcon(message.highlightApp);
            }

            // Wait before showing next message
            await new Promise(resolve => setTimeout(resolve, 2000));
        }

        // Wait before starting next example
        await new Promise(resolve => setTimeout(resolve, 4000));

        // Move to next example
        currentExampleIndex = (currentExampleIndex + 1) % chatExamples.length;
        animateMessages();
    }

    // Function to highlight app icon
    function highlightAppIcon(appName: string) {
        // Reset all icons to default opacity
        const icons = document.querySelectorAll('.icon-wrapper');
        icons.forEach(icon => {
            (icon as HTMLElement).style.opacity = '0.2';
        });

        // Highlight the relevant icon
        const targetIcon = document.querySelector(`.icon-wrapper[data-app="${appName}"]`);
        if (targetIcon) {
            (targetIcon as HTMLElement).style.opacity = '1';
        }
    }

    onMount(() => {
        animateMessages();
    });
</script>

<div class="animated-chat-container">
    {#each visibleMessages as message (message)}
        <div transition:fade={{ duration: 300 }}>
            <ChatMessage 
                role={message.type === 'user' ? 'user' : message.mateName.toLowerCase()}
                messageParts={message.appCards ? [
                    { type: 'text', content: message.text },
                    { type: 'app-cards', content: message.appCards }
                ] : undefined}
            >
                {message.text}
            </ChatMessage>
        </div>
    {/each}
</div>

<style>
    .animated-chat-container {
        width: 100%;
        max-width: 600px;
        margin: 0 auto;
        padding: 1rem;
    }
</style>