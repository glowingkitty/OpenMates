<script lang="ts">
    import AnimatedChatExamples from './AnimatedChatExamples.svelte';
    import APIexample from './APIexample.svelte';
    import { onMount, onDestroy } from 'svelte';

    // Define props for the component
    export let main_heading: string;
    export let sub_heading: string;
    export let paragraph: string;
    export let text_side: 'left' | 'right' = 'left'; // Default to left alignment
    export let target: string = '';

    // Add a prop to track visibility
    let isVisible = false;
    let highlightElement: HTMLElement;
    let observer: IntersectionObserver;

    onMount(() => {
        // In onMount, encapsulate observer logic in a small function for improved readability
        function setupObserver() {
            observer = new IntersectionObserver(
                (entries) => {
                    entries.forEach(entry => {
                        // Toggle isVisible for section animations
                        isVisible = entry.isIntersecting;
                    });
                },
                {
                    threshold: 0.7,
                    rootMargin: '-20% 0px'
                }
            );

            if (highlightElement) {
                observer.observe(highlightElement);
            }
        }

        // Initialize the observer
        setupObserver();

        return () => {
            // Ensure we unobserve and disconnect in the same place
            observer?.disconnect();
        };
    });

    onDestroy(() => {
        observer?.disconnect();
    });

    // Function to process text and preserve <mark> and <br> tags
    function processMarkTags(text: string): string {
        // Escape all HTML other than <mark> and <br>,
        // ensuring untrusted HTML won't render except for these specific tags
        const escaped = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            // Restore <mark> tags
            .replace(/&lt;mark&gt;/g, '<mark>')
            .replace(/&lt;\/mark&gt;/g, '</mark>')
            // Restore <br> tags
            .replace(/&lt;br&gt;/g, '<br>');

        return escaped;
    }

    // Function to get the correct app based on sub_heading
    function getAppForSubHeading(heading: string): string {
        switch (heading) {
            case 'Ask':
                return 'ai';
            case 'Tasks':
                return 'health';
            case 'Apps':
                return 'events';
            default:
                return '';
        }
    }
</script>

<div
    class={`highlight-container ${text_side}`}
    bind:this={highlightElement}
>
    <!-- Text content with conditional alignment -->
    <div class={`highlight-content text-${text_side}`}>
        <h3 class="subheading">{sub_heading}</h3>
        <h2 class="title">{@html processMarkTags(main_heading)}</h2>
        <p class="description">{@html processMarkTags(paragraph)}</p>
    </div>

    <!-- Visual block with background and shadow -->
    <div class="highlight-visual">
        {#if sub_heading === 'Ask'}
            <div class={`highlight-content-wrapper content-${text_side}`}>
                <div class="highlight-content-container-1">
                    <div class="provider-icons">
                        <div class="row_1">
                            <div class="icon provider-icon provider-mistral"></div>
                            <div class="icon provider-icon provider-meta"></div>
                        </div>
                        <div class="row_2">
                            <div class="icon provider-icon provider-openai"></div>
                            <div class="icon provider-icon provider-anthropic"></div>
                        </div>
                    </div>
                    <div class="center-content">
                        <div class="icon mate"></div>
                        <div class="powered-text">
                            powered by the leading<br>cloud & on-device AI models
                        </div>
                    </div>
                </div>
                <div class="highlight-content-container-2">
                    {#if target === 'for_developers'}
                        <APIexample
                            method="POST"
                            endpoint="/api/v1/mates/ask"
                            input="I am unhappy in my current job. Any ideas in what direction I could go instead?"
                            output={{
                                message: "Of course! Since you mentioned that you have a <b>background in marketing</b> and <b>enjoy storytelling</b>, we could look for roles that leverage those skills.<br>To get a better sense of direction, could you tell me:<br>1. What aspects of your previous jobs did you find most fulfilling?"
                            }}
                        />
                    {:else}
                        <AnimatedChatExamples
                            currentApp={getAppForSubHeading(sub_heading)}
                            singleExample={true}
                            inHighlight={true}
                        />
                    {/if}
                </div>
            </div>
        {/if}
        {#if sub_heading === 'Tasks'}
            <div class={`highlight-content-wrapper content-${text_side}`}>
                <div class="highlight-content-container-1">
                    <div class="inline-icons">
                        <div class="icon app-calendar"></div>
                        <div class="icon app-health"></div>
                    </div>
                    <div class="icons-text">
                        Calendar <mark>+</mark> Health
                    </div>
                </div>
                <div class="highlight-content-container-2">
                    {#if target === 'for_developers'}
                        <APIexample
                            method="POST"
                            endpoint="/api/v1/mates/ask"
                            input="What is the next available cardiologist appointment, that doesn’t collide with my calendar?"
                            output={{
                                message: "Let me quickly check your calendar and search for available doctor appointments. I will come back to you in a minute.",
                                started_tasks: ["/v1/myteam/tasks/153e0027e34d"],
                                chat_id: "13s91lads02xex75"
                            }}
                        />
                    {:else}
                        <AnimatedChatExamples
                            currentApp={getAppForSubHeading(sub_heading)}
                            singleExample={true}
                            inHighlight={true}
                        />
                    {/if}
                </div>
            </div>
        {/if}
        {#if sub_heading === 'Apps'}
            <div class={`highlight-content-wrapper content-${text_side}`}>
                <div class="highlight-content-container-1">
                    <div class="inline-icons">
                        <div class="icon app-events"></div>
                        <div class="icon skill-icon skill-search"></div>
                    </div>
                    <div class="icons-text">
                        Events | <mark>Search</mark>
                    </div>
                </div>
                <div class="highlight-content-container-2">
                    {#if target === 'for_developers'}
                        <APIexample
                            method="POST"
                            endpoint="/api/v1/apps/events/search"
                            input="AI, beginner"
                            output={{
                                events: [
                                    {
                                        title: "AI, Projects, Resources, and the Future - A Glimpse into Tomorrow",
                                        datetime: "2024-12-02T18:30:00Z"
                                    }
                            ]
                        }}
                    />
                    {:else}
                        <AnimatedChatExamples
                            currentApp={getAppForSubHeading(sub_heading)}
                            singleExample={true}
                            inHighlight={true}
                        />
                    {/if}
                </div>
            </div>
        {/if}
    </div>
</div>

<style>
    /* Container styles */
    .highlight-container {
        display: flex;
        align-items: center;
        position: relative;
        width: calc(100vw + 100px);
        left: -50px;
        margin: 80px 0;
        overflow: visible;
    }

    @media (max-width: 767px) {
        .highlight-container {
            flex-direction: column !important;
            width: 100%;
            left: 0;
            margin: 40px auto;
            padding: 0;
        }

        .highlight-content {
            width: 100% !important;
            margin: 0 0 40px 0 !important;
            text-align: center !important;
        }

        .highlight-visual {
            width: calc(100% - 60px) !important;
            min-height: 650px !important;
            height: 60vh !important;
            padding: 0 !important;
            margin: 0 20px !important;
        }


        .highlight-content-wrapper {
            padding: 0 !important;
        }
    }

    .highlight-container.left {
        flex-direction: row;
    }

    .highlight-container.right {
        flex-direction: row-reverse;
    }

    /* Content styles */
    .highlight-content {
        width: 40%;
        box-sizing: border-box;
        margin: 0 80px;
    }

    .highlight-content.text-left {
        text-align: right;
    }

    .highlight-content.text-right {
        text-align: left;
    }

    /* Visual block styles */
    .highlight-visual {
        position: relative;
        width: 60%;
        min-height: 400px;
        height: 70vh;
        background-color: var(--color-grey-20);
        border-radius: 12px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        padding: 20px 20px 0 20px;
        overflow: hidden;
        display: flex;
        align-items: center;
    }

    @media (min-width: 768px) {
        .highlight-visual {
            padding: 20px 40px 0 40px;
        }
    }

    .highlight-container.left .highlight-visual {
        padding-right: 40px;
    }

    .highlight-container.right .highlight-visual {
        padding-left: 40px;
    }

    /* Content wrapper styles */
    .highlight-content-wrapper {
        display: flex;
        width: 100%;
        max-width: 800px;
        height: 100%;
        flex-direction: column;
        position: relative;
    }

    .highlight-content-wrapper.content-left {
        margin-right: auto;
        margin-left: 0;
        padding-right: 40px;
    }

    .highlight-content-wrapper.content-right {
        margin-left: auto;
        margin-right: 0;
        padding-left: 40px;
    }


    /* Content containers */
    .highlight-content-container-1,
    .highlight-content-container-2 {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        padding: 20px;
        width: 100%;
    }

    /* Set fixed width for container 1 */
    .highlight-content-container-1 {
        flex: 0 0 auto;
        height: auto;
    }

    /* Allow container 2 to take remaining space */
    .highlight-content-container-2 {
        flex: 1;
        position: relative;
        min-height: 0;
        overflow: hidden;
        padding: 20px 20px 0 20px;
        margin-bottom: -20px;
        max-width: calc(100% - 40px);
        margin-left: auto;
        margin-right: auto;
    }

    /* Provider icons styles */
    .provider-icons {
        opacity: 0.3;
    }

    .row_1, .row_2 {
        display: flex;
        justify-content: center;
        align-items: center;
        width: auto;
        gap: 20px;
        margin-bottom: -70px;
    }

    .row_1 {
        gap: 140px;
    }

    /* Center content styles */
    .center-content {
        width: 300px;
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    .powered-text {
        color: #818181;
        text-align: center;
        margin-top: 15px;
    }

    /* Typography */
    .title {
        margin-bottom: 1rem;
    }

    .description {
        color: #6B6B6B;
    }

    /* Icon styles */
    .icon {
        filter: drop-shadow(0 0 10px rgba(0, 0, 0, 0.1));
    }

    .inline-icons {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 20px;
    }

    .icons-text {
        margin-top: 21px;
        text-align: center;
        font-weight: 700;
    }
</style>