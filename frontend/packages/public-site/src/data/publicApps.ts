import entries from '../generated/publicApps.generated.json';

export interface PublicApp {
  id: string;
  iconUrl: string;
  gradient: string;
  promptEn: string;
  promptDe: string;
}

export const publicApps = entries as PublicApp[];
