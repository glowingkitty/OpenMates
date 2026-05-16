export const PRIVACY_VIDEO_DEMO_MODE = "privacy-video";

export function isPrivacyVideoDemoMode(): boolean {
  return (
    typeof window !== "undefined" &&
    window.localStorage.getItem("openmates.demoMode") ===
      PRIVACY_VIDEO_DEMO_MODE
  );
}

export const privacyVideoDemoPrompt =
  "Create a polite email to my landlord about the broken heater at 42 Linden Street. Ask for a repair update and a callback at +49 171 000 9111. Send it from max@example.com to sophia@example.com.";

export const privacyVideoDemoAssistantResponse =
  "Subject: Repair update for the heater\n\nHello,\n\nI wanted to follow up about the broken heater issue. Could you please let me know when the repair is scheduled? You can call me back at +49 171 000 9111.\n\nBest,\nmax@example.com";

export const privacyVideoDemoAssistantHiddenResponse =
  "Subject: Repair update for the heater\n\nHello,\n\nI wanted to follow up about the broken heater issue. Could you please let me know when the repair is scheduled? You can call me back at [PHONE_1_111].\n\nBest,\n[EMAIL_1_com]";
