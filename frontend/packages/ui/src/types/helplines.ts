// Payload types of the `helplines` embed; contract: docs/plans/safety-decisions-build/wellbeing-contract.md
export interface HelplineLine {
  name: string;
  phone: string | null;
  sms: string | null;
  chat_url: string | null;
  hours: string | null;
  topics: string[];
}
