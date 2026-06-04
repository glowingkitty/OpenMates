/**
 * Deterministic billing and usage data for OpenMates demo mode.
 * Marketing recordings use this fixture after deploying to the dev web app so
 * the settings UI can show stable credits and usage rows without mutating a
 * real account's chats, purchases, or usage history.
 */
export const DEMO_MARKETING_CREDITS = 18420;
export const DEMO_MARKETING_USERNAME = 'Demo User';

export type DemoUsageMetadata = {
    title: string;
    category: string;
    icon: string;
};

export type DemoUsageEntry = {
    id: string;
    type: string;
    source: string;
    app_id: string;
    skill_id: string;
    model_used: string;
    credits: number;
    input_tokens: number;
    output_tokens: number;
    user_input_tokens: number;
    system_prompt_tokens: number;
    credits_system_prompt: number;
    credits_history: number;
    credits_response: number;
    server_provider: string;
    server_region: string;
    tool_inference_iterations: number;
    chat_id: string;
    message_id: string;
    created_at: number;
    updated_at: number;
};

export const demoUsageMetadata: Record<string, DemoUsageMetadata> = {
    'demo-usage-flights-berlin-bangkok': {
        title: 'Flights from Berlin to Bangkok',
        category: 'general_knowledge',
        icon: 'plane',
    },
    'demo-usage-ai-meetups-berlin': {
        title: 'AI workshops and meetups in Berlin',
        category: 'general_knowledge',
        icon: 'calendar',
    },
    'demo-usage-building-email': {
        title: 'Building maintenance email',
        category: 'business_development',
        icon: 'mail',
    },
};

const startOfTodaySeconds = () => {
    const now = new Date();
    return Math.floor(new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000);
};

export const buildDemoUsageEntries = (): DemoUsageEntry[] => {
    const today = startOfTodaySeconds();

    return [
        {
            id: 'demo-usage-entry-travel-search',
            type: 'chat',
            source: 'chat',
            app_id: 'travel',
            skill_id: 'search',
            model_used: 'anthropic/claude-sonnet-4-5',
            credits: 1480,
            input_tokens: 28900,
            output_tokens: 4200,
            user_input_tokens: 640,
            system_prompt_tokens: 3600,
            credits_system_prompt: 130,
            credits_history: 210,
            credits_response: 1140,
            server_provider: 'Anthropic API',
            server_region: 'EU',
            tool_inference_iterations: 4,
            chat_id: 'demo-usage-flights-berlin-bangkok',
            message_id: 'demo-usage-message-travel-search',
            created_at: today + 15 * 60 * 60 + 40 * 60,
            updated_at: today + 15 * 60 * 60 + 40 * 60,
        },
        {
            id: 'demo-usage-entry-events-search',
            type: 'chat',
            source: 'chat',
            app_id: 'events',
            skill_id: 'search',
            model_used: 'openai/gpt-5.1',
            credits: 960,
            input_tokens: 18400,
            output_tokens: 3100,
            user_input_tokens: 520,
            system_prompt_tokens: 3400,
            credits_system_prompt: 100,
            credits_history: 170,
            credits_response: 690,
            server_provider: 'OpenAI API',
            server_region: 'EU',
            tool_inference_iterations: 3,
            chat_id: 'demo-usage-ai-meetups-berlin',
            message_id: 'demo-usage-message-events-search',
            created_at: today + 11 * 60 * 60 + 20 * 60,
            updated_at: today + 11 * 60 * 60 + 20 * 60,
        },
        {
            id: 'demo-usage-entry-email',
            type: 'chat',
            source: 'chat',
            app_id: 'mail',
            skill_id: 'write',
            model_used: 'mistral/mistral-large-latest',
            credits: 340,
            input_tokens: 7200,
            output_tokens: 1250,
            user_input_tokens: 880,
            system_prompt_tokens: 2800,
            credits_system_prompt: 70,
            credits_history: 60,
            credits_response: 210,
            server_provider: 'Mistral API',
            server_region: 'EU',
            tool_inference_iterations: 0,
            chat_id: 'demo-usage-building-email',
            message_id: 'demo-usage-message-email',
            created_at: today - 24 * 60 * 60 + 16 * 60 * 60,
            updated_at: today - 24 * 60 * 60 + 16 * 60 * 60,
        },
    ];
};
