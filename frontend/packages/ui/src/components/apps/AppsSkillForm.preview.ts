import type { AppsSkillDetails } from '../../types/appsWorkspace';

const metadata: AppsSkillDetails = {
  app_id: 'events', skill_id: 'search', slug: 'search', name: 'Search events',
  name_translation_key: 'events.search', description: 'Find events near you.',
  description_translation_key: 'events.search.description', icon_image: null,
  input_schema: {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', minItems: 1, items: { type: 'object', required: ['query', 'location'], properties: {
        query: { type: 'string', title: 'What', minLength: 1 },
        location: { type: 'string', title: 'Where' },
        relevance_criteria: { type: 'string', maxLength: 1000, description: 'Optional concise natural-language event-ranking goal, separate from the event query.', 'x-ui': { basic: true } },
        start_date: { type: 'string', format: 'date', title: 'Start date' },
        end_date: { type: 'string', format: 'date', title: 'End date' },
      } } },
      provider: { type: 'string', enum: ['default', 'alternative'], default: 'default' },
    },
  },
  primary_fields: ['requests[].query', 'requests[].location'],
  defaults: { requests: [{ start_date: '2026-10-01', end_date: '2026-10-07' }], provider: 'default' },
  pricing: null, providers: [], models: [], anonymous_allowed: true,
  execution_available: true, unavailable_reason: null, execution_mode: 'sync',
};

/** Faithful request-shape excerpt from travel.search_connections in app.yml. */
export const travelMetadata: AppsSkillDetails = {
  ...metadata,
  app_id: 'travel', skill_id: 'search_connections', slug: 'search-connections', name: 'Search connections',
  input_schema: {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', items: { type: 'object', properties: {
        legs: { type: 'array', items: { type: 'object', required: ['origin', 'destination', 'date'], properties: {
          origin: { type: 'string', title: 'Origin', 'x-ui': { basic: true, control: 'location', location_mode: 'place' } },
          destination: { type: 'string', title: 'Destination', 'x-ui': { basic: true, control: 'location', location_mode: 'place' } },
          date: { type: 'string', title: 'Departure date', format: 'date', 'x-ui': { basic: true } },
        } } },
        transport_methods: { type: 'array', items: { type: 'string', enum: ['airplane', 'train', 'bus', 'boat'] }, default: ['airplane'] },
      } } },
    },
  },
  primary_fields: ['requests[].legs[].origin', 'requests[].legs[].destination'],
  defaults: { requests: [{ transport_methods: ['airplane'] }] },
  anonymous_allowed: true,
};

/** Faithful date-range excerpt from travel.search_stays in app.yml. */
export const staysMetadata: AppsSkillDetails = {
  ...metadata,
  app_id: 'travel', skill_id: 'search_stays', slug: 'search-stays', name: 'Search stays',
  input_schema: {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', items: { type: 'object', required: ['query', 'check_in_date', 'check_out_date'], 'x-ui': {
        control: 'date-range', start_field: 'check_in_date', end_field: 'check_out_date', max_offset_days: 365,
      }, properties: {
        query: { type: 'string', title: 'Destination' },
        check_in_date: { type: 'string', title: 'Check-in', format: 'date' },
        check_out_date: { type: 'string', title: 'Check-out', format: 'date' },
        adults: { type: 'integer', default: 2 },
      } } },
    },
  },
  primary_fields: ['requests[].query', 'requests[].check_in_date'],
  defaults: { requests: [{ adults: 2 }] },
  anonymous_allowed: false,
};

/** Request schema and public rate from audio.generate and ElevenLabs metadata. */
export const audioGenerateMetadata: AppsSkillDetails = {
  ...metadata,
  app_id: 'audio', skill_id: 'generate', slug: 'generate', name: 'Generate sound',
  input_schema: {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', minItems: 1, maxItems: 5, items: { type: 'object', required: ['prompt', 'provider'], properties: {
        prompt: { type: 'string', title: 'Prompt', minLength: 1, maxLength: 400, 'x-ui': { basic: true, control: 'textarea' } },
        provider: { type: 'string', enum: ['elevenlabs'], default: 'elevenlabs', 'x-ui': { basic: false } },
        duration_seconds: { type: 'number', minimum: 0.5, maximum: 2, default: 1, 'x-ui': { basic: false } },
        prompt_influence: { type: 'number', minimum: 0, maximum: 1, default: 0.3, 'x-ui': { basic: false } },
        loop: { type: 'boolean', default: false, 'x-ui': { basic: false } },
        output_format: { type: 'string', enum: ['mp3_22050_32', 'mp3_24000_48', 'mp3_44100_32', 'mp3_44100_64', 'mp3_44100_96', 'mp3_44100_128', 'mp3_44100_192'], default: 'mp3_44100_128', 'x-ui': { basic: false } },
        model: { type: 'string', enum: ['eleven_text_to_sound_v2'], default: 'eleven_text_to_sound_v2', 'x-ui': { basic: false } },
      } } },
    },
  },
  primary_fields: ['requests[].prompt'],
  defaults: { requests: [{ provider: 'elevenlabs', duration_seconds: 1, prompt_influence: 0.3, loop: false, output_format: 'mp3_44100_128', model: 'eleven_text_to_sound_v2' }] },
  pricing: { per_second: 20 },
  providers: [{ id: 'elevenlabs', name: 'ElevenLabs' }],
  models: [{ id: 'eleven_text_to_sound_v2', name: 'ElevenLabs Text to Sound v2', provider_id: 'elevenlabs', provider_name: 'ElevenLabs', pricing: { per_second: 20 } }],
  anonymous_allowed: false,
};

/** Public request and named unit price from music.generate in app.yml. */
export const musicGenerateMetadata: AppsSkillDetails = {
  ...metadata,
  app_id: 'music', skill_id: 'generate', slug: 'generate', name: 'Generate music',
  input_schema: {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', items: { type: 'object', required: ['prompt'], properties: {
        prompt: { type: 'string', title: 'Prompt', 'x-ui': { basic: true } },
        mode: { type: 'string', enum: ['song', 'instrumental', 'background', 'loop', 'jingle'], default: 'background', 'x-ui': { basic: true } },
        style: { type: 'string', 'x-ui': { basic: true } },
        duration_seconds: { type: 'integer', minimum: 3, maximum: 184, default: 30, 'x-ui': { basic: true } },
        model: { type: 'string', enum: ['lyria-3-pro-preview', 'lyria-3-clip-preview', 'lyria-002'], default: 'lyria-3-pro-preview', 'x-ui': { basic: false } },
      } } },
    },
  },
  primary_fields: ['requests[].prompt', 'requests[].mode'],
  defaults: { requests: [{ mode: 'background', duration_seconds: 30, model: 'lyria-3-pro-preview' }] },
  pricing: { per_unit: { credits: 120, unit_name: 'track' } },
  providers: [{ id: 'google', name: 'Google' }],
  models: [],
  anonymous_allowed: false,
};

/** Faithful request-shape excerpt from health.search_appointments in app.yml. */
export const healthMetadata: AppsSkillDetails = {
  ...metadata,
  app_id: 'health', skill_id: 'search_appointments', slug: 'search-appointments', name: 'Search appointments',
  input_schema: {
    type: 'object', required: ['requests'], properties: {
      requests: { type: 'array', 'x-ui': { basic: true }, items: { type: 'object', required: ['speciality', 'city'], properties: {
        speciality: { type: 'string', 'x-ui': { basic: true } },
        city: { type: 'string', 'x-ui': { basic: true, control: 'location', location_mode: 'city' } },
        provider_platform: { type: 'string', enum: ['both', 'doctolib_de', 'jameda'], default: 'both', 'x-ui': { basic: false } },
        insurance_sector: { type: 'string', enum: ['public', 'private'], 'x-ui': { basic: true } },
        telehealth: { type: 'boolean', default: false, 'x-ui': { basic: false } },
        language: { type: 'string', 'x-ui': { basic: false } },
        days_ahead: { type: 'integer', enum: [1, 3, 7], default: 7, 'x-ui': { basic: true } },
        max_doctors: { type: 'integer', minimum: 1, maximum: 30, default: 10, 'x-ui': { basic: false } },
        visit_motive_category: { type: 'string', enum: ['general', 'checkup', 'vaccination', 'followup'], 'x-ui': { basic: false } },
      } } },
    },
  },
  primary_fields: ['requests[].speciality', 'requests[].city'],
  defaults: { requests: [{ provider_platform: 'both', days_ahead: 7, max_doctors: 10, telehealth: false }] },
  anonymous_allowed: false,
};

const dispatch = async (input: Record<string, unknown>) => {
  window.dispatchEvent(new CustomEvent('apps-skill-preview-submit', { detail: input }));
};

export default {
  metadata,
  onSubmit: dispatch,
};

export const variants = {
  guestBlocked: { metadata, guest: true, guestEligibility: { allowed: false, reason: 'budget_exhausted' }, onSignup: () => window.dispatchEvent(new Event('apps-skill-preview-signup')), onSubmit: async () => {} },
  unavailable: { metadata: { ...metadata, execution_available: false, unavailable_reason: 'PROVIDER_UNAVAILABLE' }, onSubmit: async () => {} },
  travel: { metadata: travelMetadata, onSubmit: dispatch },
  travelGuest: { metadata: travelMetadata, guest: true, guestEligibility: { allowed: true, reason: null }, onSubmit: dispatch },
  stays: { metadata: staysMetadata, onSubmit: dispatch },
  audioGenerate: { metadata: audioGenerateMetadata, onSubmit: dispatch },
  musicGenerate: { metadata: musicGenerateMetadata, onSubmit: dispatch },
  health: { metadata: healthMetadata, onSubmit: dispatch },
};
