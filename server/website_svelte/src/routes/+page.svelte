<script lang="ts">
    import Icon from './Icon.svelte';
    import Button from './Button.svelte';
    import Field from './Field.svelte';
    import ChatMessage from './ChatMessage.svelte';
    import HealthAppCard from './cards/HealthAppCard.svelte';
    import EventAppCard from './cards/EventAppCard.svelte';

    // Define icon groups
    const endpointIcons = [
        'app', 'billing', 'chat', 'mate', 'project', 'server',
        'skill', 'task', 'team', 'user', 'workflow'
    ];

    const appIcons = [
        'ai', 'health', 'lifecoaching', 'nutrition', 'finance', 'fitness',
        'legal', 'weather', 'travel', 'news', 'jobs', 'files', 'home',
        'docs', 'slides', 'sheets', 'notes', 'whiteboards', 'diagrams',
        'events', 'code', 'calendar', 'mail', 'reminder', 'business',
        'web', 'videos', 'audio', 'maps', 'design', 'pcbdesign',
        'pdfeditor', 'shopping', 'photos', 'publishing', 'socialmedia',
        'projectmanagement', 'messages', 'books', 'plants', 'beauty',
        'hosting', 'fashion', 'shipping', 'time', 'tv', 'movies',
        'secrets', 'study', 'contacts', 'calculator', 'games', 'language'
    ];

    const providerIcons = [
        'openai', 'anthropic', 'meta', 'mistral'
    ];

    const skillIcons = [
        'search', 'create', 'message'
    ];

    const focusIcons = [
        'insights'
    ];

    // Add example data for chat messages
    const chatExamples = [
        {
            type: 'user' as const,
            text: 'I am unhappy in my current job. Any ideas in what direction I could go instead?'
        },
        {
            type: 'mate' as const,
            mateName: 'Burton',
            mateProfile: 'burton',
            text: 'Of course! Since you mentioned that you have a background in marketing and enjoy storytelling, we could look for roles that leverage those skills.\n\nTo get a better sense of direction, could you tell me:\n1. What aspects of your previous jobs did you find most fulfilling?'
        }
    ];
</script>

<div class="design-system-header">
    <h1>OpenMates<br>Design System</h1>
</div>

<section class="section">
    <h2 class="section-title">Colors</h2>
    <div id="base-colors" class="color-palette">
        <!-- Base colors will be rendered here -->
    </div>
    
    <div id="app-colors" class="color-palette">
        <!-- App colors will be rendered here -->
    </div>
</section>

<section class="section">
    <h2 class="section-title">Icons - OpenMates Endpoints</h2>
    <div class="icon-container">
        {#each endpointIcons as name}
            <div class="icon-wrapper">
                <Icon {name} />
                <span class="icon-label">icon.{name}</span>
            </div>
        {/each}
    </div>
</section>

<section class="section">
    <h2 class="section-title">Icons - Apps</h2>
    <div class="icon-container">
        {#each appIcons as name}
            <div class="icon-wrapper">
                <Icon name={name} type="app" />
                <span class="icon-label">.app-{name}</span>
            </div>
        {/each}
    </div>
</section>

<section class="section">
    <h2 class="section-title">Icons - Providers</h2>
    <div class="icon-container">
        {#each providerIcons as name}
            <div class="icon-wrapper">
                <Icon name={name} type="provider" />
                <span class="icon-label">.provider-{name}</span>
            </div>
        {/each}
    </div>
</section>

<section class="section">
    <h2 class="section-title">Icons - Skills</h2>
    <div class="icon-container">
        {#each skillIcons as name}
            <div class="icon-wrapper">
                <Icon name={name} type="skill" />
                <span class="icon-label">.skill-{name}</span>
            </div>
        {/each}
    </div>
</section>

<section class="section">
    <h2 class="section-title">Icons - Focuses</h2>
    <div class="icon-container">
        {#each focusIcons as name}
            <div class="icon-wrapper">
                <Icon name={name} type="focus" />
                <span class="icon-label">.focus-{name}</span>
            </div>
        {/each}
    </div>
</section>

<section class="section">
    <h2 class="section-title">Buttons</h2>
    <div class="button-container">
        <Button>Primary</Button>
        <Button variant="secondary">Secondary</Button>
    </div>
</section>

<section class="section">
    <h2 class="section-title">Fields</h2>
    <Field type="search" placeholder="Search..." variant="search" />
    <Field type="text" placeholder="Enter API Key..." variant="apikey" />
    <Field type="text" placeholder="Enter Team Slug..." variant="teamslug" />
    <Field type="email" placeholder="Enter your e-mail address..." variant="email" />
</section>

<section class="section">
    <h2 class="section-title">Chat</h2>
    <div class="container">
        {#each chatExamples as message}
            <ChatMessage 
                type={message.type} 
                mateName={message.type === 'mate' ? message.mateName : undefined}
                mateProfile={message.type === 'mate' ? message.mateProfile : undefined}
            >
                {message.text}
            </ChatMessage>
        {/each}

        <button class="processing-details">
            <span class="icon app-calendar inline"></span>
            <span class="icon app-health inline"></span>
            Used <strong>2 apps</strong> ...
        </button>
    </div>
</section>

<section class="section">
    <h2 class="section-title">App Cards</h2>
    <div class="container">
        <div class="example_container">
            <HealthAppCard
                size="large"
                date="Wed, Dec 12"
                time="9:00 - 10:00"
                doctorName="Dr. Van Hausen"
                specialty="Cardiologist"
                rating={4.2}
                ratingCount={85}
                showCalendar={true}
                appointments={[
                    {start: 0, end: 1, type: 'dashed'},
                    {start: 4, end: 6, type: 'solid'}
                ]}
            />
            <div class="app-card-description">Health - Appointment (large)</div>
        </div>

        <div class="example_container">
            <EventAppCard
                size="small"
                date="Today"
                time="18:30"
                eventName="Book Lovers' Social: An Evening of Reading and Discussion"
                participants={12}
                imageUrl="../../public/images/examples/group1.jpg"
            />
            <div class="app-card-description">Events - Event (small)</div>
        </div>
    </div>
</section>

<style>
    .design-system-header {
        text-align: center;
        margin-bottom: 60px;
    }

    .section {
        width: 100%;
        max-width: 1200px;
        margin-bottom: 60px;
    }

    .section-title {
        font-size: 1.8rem;
        color: #444;
        margin-bottom: 30px;
        padding-bottom: 10px;
        border-bottom: 2px solid #ddd;
    }

    .icon-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
        gap: 25px;
        padding: 20px;
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    .icon-wrapper {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .icon-label {
        margin-top: 8px;
        font-size: 0.8rem;
        color: #666;
        word-break: break-word;
    }

    .button-container {
        display: flex;
        gap: 10px;
        padding: 20px;
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }
</style>
