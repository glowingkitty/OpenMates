// Preview states for the helpline card (all data is synthetic placeholder data):
// /dev/preview/embeds/wellbeing/HelplineCard?chrome=0  (DE, 2 lines)
// &variant=us (3 lines incl. text and chat), &variant=emergency_only (no lines).
import type { HelplineLine } from '../../../types/helplines';

const exampleLine = (overrides: Partial<HelplineLine>): HelplineLine => ({
  name: 'Example Helpline',
  phone: null,
  sms: null,
  chat_url: null,
  hours: null,
  topics: [],
  ...overrides,
});

const props = {
  country: 'DE',
  language: 'de',
  source: 'throughline' as const,
  emergency_number: '112',
  directory_url: 'https://example.org/helplines',
  lines: [
    exampleLine({ name: 'Example Helpline One', phone: '0800 000 0000', hours: 'Rund um die Uhr, kostenlos', topics: ['crisis'] }),
    exampleLine({ name: 'Example Helpline Two', phone: '0800 000 0001', chat_url: 'https://example.org/chat', hours: 'Mo-Fr 10-22 Uhr', topics: ['youth'] }),
  ],
};

export default props;
export const variants = {
  us: {
    ...props,
    country: 'US',
    language: 'en',
    emergency_number: '911',
    lines: [
      exampleLine({ name: 'Example Crisis Line', phone: '000', sms: '000000', chat_url: 'https://example.org/chat', hours: '24/7, free and confidential', topics: ['crisis'] }),
      exampleLine({ name: 'Example Text Line', sms: '000001', hours: '24/7', topics: ['crisis'] }),
      exampleLine({ name: 'Example Veterans Line, a deliberately long name that has to wrap', phone: '000 000 0002', chat_url: 'https://example.org/veterans', hours: '24/7', topics: ['veterans'] }),
    ],
  },
  emergency_only: { ...props, source: 'emergency_only' as const, country: 'GB', language: 'en', emergency_number: '999', lines: [] as HelplineLine[] },
};
