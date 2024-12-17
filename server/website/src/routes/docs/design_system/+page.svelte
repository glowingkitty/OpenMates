<script lang="ts">
    import Header from '../../components/Header.svelte';
    import Icon from '../../components/Icon.svelte';
    import Button from '../../components/Button.svelte';
    import Field from '../../components/Field.svelte';
    import ChatMessage from '../../components/ChatMessage.svelte';
    import HealthAppCard from '../../components/cards/HealthAppCard.svelte';
    import EventAppCard from '../../components/cards/EventAppCard.svelte';
    import ProcessingDetails from '../../components/ProcessingDetails.svelte';

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

    // Update the chatExamples array to include more examples
    const chatExamples = [
        // Career advice conversation
        {
            type: 'user' as const,
            text: 'I am unhappy in my current job. Any ideas in what direction I could go instead?'
        },
        {
            type: 'mate' as const,
            mateName: 'Burton',
            mateProfile: 'burton',
            text: 'Of course! Since you mentioned that you have a background in marketing and enjoy storytelling, we could look for roles that leverage those skills.\n\nTo get a better sense of direction, could you tell me:\n1. What aspects of your previous jobs did you find most fulfilling?'
        },
        {
            type: 'user' as const,
            text: 'I really enjoyed creating marketing campaigns and seeing them come to life. The creative process of storytelling and connecting with audiences was particularly fulfilling.'
        },

        // Events conversation
        {
            type: 'user' as const,
            text: 'What events are happening the coming days?'
        },
        {
            type: 'mate' as const,
            mateName: 'Lisa',
            mateProfile: 'lisa',
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
        },

        // Health appointment conversation
        {
            type: 'user' as const,
            text: "What is the next available cardiologist appointment, that doesn't collide with my calendar?"
        },
        {
            type: 'mate' as const,
            mateName: 'Melvin',
            mateProfile: 'melvin',
            text: 'Let me quickly check your calendar and search for available doctor appointments. I will come back to you in a minute.'
        },
        {
            type: 'mate' as const,
            mateName: 'Melvin',
            mateProfile: 'melvin',
            text: 'The best appointment I could find is tomorrow at 9:00. Doesn\'t collide with your product launch meeting later that day.',
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
    ];

    // Helper function to get computed hex color from CSS variable
    function getCssVarColor(varName: string): string {
        // Get color from CSS variable, defaulting to empty string if not found
        const color = getComputedStyle(document.documentElement)
            .getPropertyValue(varName)
            .trim();
        return color;
    }

    // Function to load base colors
    function loadBaseColors(): Array<{name: string, startColor: string, endColor: string}> {
        // Define base color variables
        const baseColors = [
            'color-primary',
            'icon-background',
            'icon-focus-background'
        ];

        const colors = baseColors.map(colorName => ({
            name: colorName,
            startColor: getCssVarColor(`--${colorName}-start`),
            endColor: getCssVarColor(`--${colorName}-end`)
        }));

        // Add icon border color separately since it's not a gradient
        const borderColor = getCssVarColor('--icon-border-color');
        colors.push({
            name: 'icon-border-color',
            startColor: borderColor,
            endColor: borderColor
        });

        return colors;
    }

    // Function to load app colors
    function loadAppColors(): Array<{name: string, startColor: string, endColor: string}> {
        const appColors: Array<{name: string, startColor: string, endColor: string}> = [];
        
        // Get all CSS custom properties that match app color pattern
        const styleSheets = document.styleSheets;
        for (const sheet of styleSheets) {
            try {
                const rules = sheet.cssRules || sheet.rules;
                for (const rule of rules) {
                    if (rule instanceof CSSStyleRule && rule.selectorText === ':root') {
                        const style = rule.style;
                        const appColorSet = new Set<string>();
                        
                        for (let i = 0; i < style.length; i++) {
                            const prop = style[i];
                            if (prop.startsWith('--color-app-') && !prop.endsWith('-start') && !prop.endsWith('-end')) {
                                appColorSet.add(prop.replace('--color-app-', ''));
                            }
                        }

                        appColorSet.forEach(colorName => {
                            appColors.push({
                                name: colorName,
                                startColor: getCssVarColor(`--color-app-${colorName}-start`),
                                endColor: getCssVarColor(`--color-app-${colorName}-end`)
                            });
                        });
                    }
                }
            } catch (e) {
                console.error('Error accessing stylesheet:', e);
            }
        }

        return appColors;
    }

    let baseColors: Array<{name: string, startColor: string, endColor: string}> = [];
    let appColors: Array<{name: string, startColor: string, endColor: string}> = [];

    // Load colors when component mounts
    import { onMount } from 'svelte';
    onMount(() => {
        baseColors = loadBaseColors();
        appColors = loadAppColors();
    });
</script>

<Header />

<h1 class="text-center">Design System</h1>

<h2 class="text-center">Learn how OpenMates is designed & built up.</h2>

<section class="section">
    <h2 class="section-title">Colors</h2>
    
    <h3 class="subsection-title">Base Colors</h3>
    <div id="base-colors" class="color-palette">
        {#each baseColors as color}
            <div class="color-item">
                <div class="color-info">
                    <div class="gradient-var">--{color.name}</div>
                    <div 
                        class="gradient-preview" 
                        style="background: linear-gradient(to right, {color.startColor}, {color.endColor})"
                    ></div>
                    <div class="color-blocks">
                        <div class="color-block">
                            <div class="color-sample" style="background: {color.startColor}"></div>
                            <div class="color-text">
                                <div class="var-name">--{color.name}-start</div>
                                <div class="hex-code">{color.startColor}</div>
                            </div>
                        </div>
                        <div class="color-block">
                            <div class="color-sample" style="background: {color.endColor}"></div>
                            <div class="color-text">
                                <div class="var-name">--{color.name}-end</div>
                                <div class="hex-code">{color.endColor}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        {/each}
    </div>

    <h3 class="subsection-title">App Colors</h3>
    <div id="app-colors" class="color-palette">
        {#each appColors as color}
            <div class="color-item">
                <div class="color-info">
                    <div class="gradient-var">--color-app-{color.name}</div>
                    <div 
                        class="gradient-preview" 
                        style="background: linear-gradient(to right, {color.startColor}, {color.endColor})"
                    ></div>
                    <div class="color-blocks">
                        <div class="color-block">
                            <div class="color-sample" style="background: {color.startColor}"></div>
                            <div class="color-text">
                                <div class="var-name">--color-app-{color.name}-start</div>
                                <div class="hex-code">{color.startColor}</div>
                            </div>
                        </div>
                        <div class="color-block">
                            <div class="color-sample" style="background: {color.endColor}"></div>
                            <div class="color-text">
                                <div class="var-name">--color-app-{color.name}-end</div>
                                <div class="hex-code">{color.endColor}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        {/each}
    </div>
</section>

<section class="section">
    <h2 class="section-title">Typography</h2>
    <div class="typography-container">
        <div class="typography-example">
            <h1>H1<br><mark>With highlight</mark></h1>
            <div class="typography-info">
                font-family: var(--font-primary) (Lexend Deca)<br>
                font-size: var(--font-size-h1) (60px)<br>
                font-weight: var(--font-weight-extra-bold) (800)<br>
                line-height: var(--line-height-normal)<br>
                color: var(--color-font-primary)
            </div>
        </div>

        <div class="typography-example">
            <h2>H2 <mark>With highlight</mark></h2>
            <div class="typography-info">
                font-family: var(--font-primary) (Lexend Deca)<br>
                font-size: var(--font-size-h2) (30px)<br>
                font-weight: var(--font-weight-bold) (700)<br>
                line-height: var(--line-height-normal)
            </div>
        </div>

        <div class="typography-example">
            <h3>H3</h3>
            <div class="typography-info">
                font-family: var(--font-primary) (Lexend Deca)<br>
                font-size: var(--font-size-h3) (20px)<br>
                font-weight: var(--font-weight-bold) (700)<br>
                line-height: var(--line-height-normal)<br>
                color: var(--color-font-secondary)
            </div>
        </div>

        <div class="typography-example">
            <h4>H4</h4>
            <div class="typography-info">
                font-family: var(--font-primary) (Lexend Deca)<br>
                font-size: var(--font-size-h4) (16px)<br>
                font-weight: var(--font-weight-bold) (700)<br>
                line-height: var(--line-height-normal)<br>
                color: var(--color-font-tertiary)
            </div>
        </div>

        <div class="typography-example">
            <p>Regular text - This is an example from OpenMates with body text</p>
            <div class="typography-info">
                font-family: var(--font-primary) (Lexend Deca)<br>
                font-size: var(--font-size-p) (16px)<br>
                font-weight: var(--font-weight-p) (500)<br>
                line-height: var(--line-height-normal)<br>
                font-style: var(--font-style-normal)
            </div>
        </div>
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
    <h2 class="section-title">Separators</h2>
    <div class="large-separator"></div>
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
    <h2 class="section-title">Mates</h2>
    <div class="mates-container">
        <div class="mate-wrapper">
            <div class="mate-profile burton"></div>
            <div class="mate-name">Burton</div>
            <div class="mate-specialty">Business Development</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile sophia"></div>
            <div class="mate-name">Sophia</div>
            <div class="mate-specialty">Software Developer</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile melvin"></div>
            <div class="mate-name">Melvin</div>
            <div class="mate-specialty">Medical Doctor</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile finn"></div>
            <div class="mate-name">Finn</div>
            <div class="mate-specialty">Finance</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile elton"></div>
            <div class="mate-name">Elton</div>
            <div class="mate-specialty">Electrical Engineering</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile denise"></div>
            <div class="mate-name">Denise</div>
            <div class="mate-specialty">Design</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile mark"></div>
            <div class="mate-name">Mark</div>
            <div class="mate-specialty">Marketing</div>
        </div>
        <div class="mate-wrapper">
            <div class="mate-profile colin"></div>
            <div class="mate-name">Colin</div>
            <div class="mate-specialty">Cook & Nutritionist</div>
        </div>
    </div>
</section>



<section class="section">
    <h2 class="section-title">App Cards</h2>
    <div class="container">
        <div class="example_container">
            <HealthAppCard
                size="large"
                date="Wed, Dec 12"
                start="9:00"
                end="10:00"
                doctorName="Dr. Van Hausen"
                specialty="Cardiologist"
                rating={4.2}
                ratingCount={85}
                showCalendar={true}
                existingAppointments={[
                    {start: "13:00", end: "15:00"}
                ]}
            />
            <div class="app-card-description">Health - Appointment (large)</div>
        </div>

        <div class="example_container">
            <HealthAppCard
                size="small"
                date="Wed, Dec 12"
                start="9:00"
                end="10:00"
                doctorName="Dr. Van Hausen"
                specialty="Cardiologist"
                rating={4.2}
                ratingCount={85}
            />
            <div class="app-card-description">Health - Appointment (small)</div>
        </div>

        <div class="example_container">
            <EventAppCard
                size="small"
                date="Today"
                time="18:30"
                eventName="Book Lovers' Social: An Evening of Reading and Discussion"
                participants={12}
                imageUrl="/images/examples/group1.jpg"
            />
            <div class="app-card-description">Events - Event (small)</div>
        </div>

        <div class="example_container">
            <EventAppCard
                size="small"
                date="Dec 15"
                time="19:00"
                eventName="TechTalk: AI in Everyday Business"
                participants={76}
                imageUrl="/images/examples/group2.jpg"
            />
            <div class="app-card-description">Events - Event (small)</div>
        </div>
    </div>
</section>

<section class="section">
    <h2 class="section-title">Chat</h2>
    <div class="container">
        <!-- Chat message - mate -->
        <div class="example_container">
            <ChatMessage role="burton">
                Of course! Since you mentioned that you have a <bold>background in marketing</bold> and <bold>enjoy storytelling</bold>, we could look for roles that leverage those skills. To get a better sense of direction, could you tell me:
                <ol>
                    <li>What aspects of your previous jobs did you find most fulfilling?</li>
                </ol>
            </ChatMessage>
            <div class="app-card-description">Chat message - mate</div>
        </div>

        <!-- Chat message - user -->
        <div class="example_container">
            <ChatMessage role="user">
                I really enjoyed creating marketing campaigns and seeing them come to life. The creative process of storytelling and connecting with audiences was particularly fulfilling.
            </ChatMessage>
            <div class="app-card-description">Chat message - user</div>
        </div>

        <!-- Loading preferences -->
        <div class="example_container">
            <ProcessingDetails
                type="loaded_preferences"
                appNames={['Jobs']}
            />
            <div class="app-card-description">Loaded preferences</div>
        </div>

        <!-- Using app -->
        <div class="example_container">
            <ProcessingDetails
                type="using_apps"
                in_progress={true}
                appNames={['Events']}
            />
            <div class="app-card-description">Using app</div>
        </div>

        <!-- Using multiple apps -->
        <div class="example_container">
            <ProcessingDetails
                type="using_apps"
                in_progress={true}
                appNames={['Calendar', 'Health']}
            />
            <div class="app-card-description">Using multiple apps</div>
        </div>

        <!-- Chat conversation with loaded preferences -->
        <div class="example_container">
            <ChatMessage role="user">
                I am unhappy in my current job. Any ideas in what direction I could go instead?
            </ChatMessage>
            <ProcessingDetails
                type="started_focus"
                appNames={['Jobs']}
                focusName="Career insights"
                focusIcon="insights"
            />
            <ProcessingDetails
                type="loaded_preferences"
                appNames={['Jobs']}
            />
            <ChatMessage role="burton">
                Of course! Since you mentioned that you have a <bold>background in marketing</bold> and <bold>enjoy storytelling</bold>, we could look for roles that leverage those skills. To get a better sense of direction, could you tell me:
                <ol>
                    <li>What aspects of your previous jobs did you find most fulfilling?</li>
                </ol>
            </ChatMessage>
            <div class="app-card-description">Chat conversation with loaded preferences</div>
        </div>

        <!-- Chat conversation with using events app -->
        <div class="example_container">
            <ChatMessage role="user">
                What events are happening the coming days?
            </ChatMessage>
            <ProcessingDetails
                type="using_apps"
                in_progress={false}
                appNames={['Events']}
            />
            <ChatMessage
                role="lisa"
                messageParts={[
                    {
                        type: 'text',
                        content: 'There are some exciting events going on the coming days! Both to help you learn for a better career and to socialize more.' 
                    },
                    {
                        type: 'app-cards',
                        content: [
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
                    },
                    {
                        type: 'text',
                        content: 'I hope you find something interesting!'
                    }
                ]}
            />
            <div class="app-card-description">Chat conversation with using events app</div>
        </div>

        <!-- Chat conversation with using 2 apps -->
        <div class="example_container">
            <ChatMessage role="user">
                What is the next available cardiologist appointment, that doesn't collide with my calendar?
            </ChatMessage>
            <ChatMessage role="melvin">
                Let me quickly check your calendar and search for available doctor appointments. I will come back to you in a minute.
            </ChatMessage>
            <ProcessingDetails
                type="using_apps"
                in_progress={false}
                appNames={['Calendar', 'Health']}
            />
            <ChatMessage
                role="melvin"
                messageParts={[
                    {
                        type: 'text',
                        content: 'The best appointment I could find is <bold>tomorrow at 9:00</bold>. Doesn\'t collide with your product launch meeting later that day.' 
                    },
                    {
                        type: 'app-cards',
                        content: [
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
                            },
                            {
                                component: HealthAppCard,
                                props: {
                                    size: 'large',
                                    date: 'Thu, Dec 13',
                                    start: '11:30',
                                    end: '12:30',
                                    doctorName: 'Dr. Williams',
                                    specialty: 'Cardiologist',
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
                                    date: 'Fri, Dec 14',
                                    start: '15:00',
                                    end: '16:00',
                                    doctorName: 'Dr. Chen',
                                    specialty: 'Cardiologist',
                                    rating: 4.6,
                                    ratingCount: 93,
                                    showCalendar: true,
                                    existingAppointments: [
                                        {start: '10:00', end: '12:00'}
                                    ]
                                }
                            }
                        ]
                    },
                    {
                        type: 'text',
                        content: 'Does any of them sound good to you?'
                    }
                ]}
            />
            <div class="app-card-description">Chat conversation with using 2 apps</div>
        </div>
    </div>
</section>



<style>
    .section {
        max-width: 1200px;
        margin: 0 auto 60px;
        padding: 0 40px;
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

    .container {
        display: flex;
        flex-wrap: wrap;
        gap: 20px;
        justify-content: center;
        background-color: white;
        padding: 30px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        width: 100%;
    }

    .example_container {
        display: flex;
        flex-direction: column;
        align-items: center;
        flex: 1;
        min-width: 300px;
        max-width: calc(50% - 10px);
        margin: 0;
    }

    .app-card-description {
        margin-top: 10px;
        color: var(--color-font-secondary);
        font-size: 0.9rem;
        font-family: var(--font-primary);
    }

    .typography-container {
        background-color: white;
        padding: 30px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    .typography-example {
        margin-bottom: 30px;
    }

    .typography-info {
        margin-top: 10px;
        font-family: monospace;
        font-size: 0.8rem;
        color: #666;
        padding: 8px;
        background-color: #f5f5f5;
        border-radius: 4px;
    }

    .typography-example p {
        margin: 0;
    }

    .mates-container {
        display: flex;
        flex-wrap: wrap;
        gap: 30px;
        justify-content: center;
        padding: 20px;
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    .mate-wrapper {
        min-width: 150px;
        flex: 0 1 auto;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .mate-name {
        font-size: 1.2rem;
        font-weight: 600;
        color: var(--color-font-primary);
        margin-bottom: 5px;
    }

    .mate-specialty {
        font-size: 0.9rem;
        color: var(--color-font-secondary);
    }

    .subsection-title {
        font-size: 1.3rem;
        color: #555;
        margin: 30px 0 15px;
        padding-left: 15px;
        border-left: 4px solid #ddd;
    }

    .color-palette {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 25px;
        padding: 20px;
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    .color-item {
        background: white;
        border-radius: 8px;
        padding: 12px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        height: 100%;
    }

    .color-info {
        display: flex;
        flex-direction: column;
        height: 100%;
    }

    .gradient-var {
        font-family: monospace;
        font-size: 0.8rem;
        color: #666;
        margin-bottom: 8px;
        padding-bottom: 4px;
        border-bottom: 1px solid #eee;
    }

    .gradient-preview {
        width: 100%;
        height: 16px;
        border-radius: 3px;
        margin-bottom: 8px;
        border: 1px solid rgba(0, 0, 0, 0.1);
        background-size: 100% 100%;
    }

    .color-blocks {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .color-block {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .color-sample {
        width: 16px;
        height: 16px;
        border-radius: 3px;
        border: 1px solid rgba(0, 0, 0, 0.1);
    }

    .color-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .var-name {
        font-family: monospace;
        font-size: 0.75rem;
        color: #666;
    }

    .hex-code {
        font-family: monospace;
        font-size: 0.75rem;
        font-weight: 600;
        color: #333;
    }
</style>
