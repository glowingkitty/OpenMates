import entries from '../generated/publicApps.generated.json';

export interface PublicApp {
  id: string;
  iconUrl: string;
  gradient: string;
  capability: { type: 'skill' | 'focus' | 'artifact' | 'app'; id: string };
  exampleChatId: string;
  promptEn: string;
  promptDe: string;
}

export const publicApps = entries as PublicApp[];
