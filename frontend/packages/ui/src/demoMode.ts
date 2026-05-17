export const PRIVACY_VIDEO_DEMO_MODE = "privacy-video";

export function isPrivacyVideoDemoMode(): boolean {
  return (
    typeof window !== "undefined" &&
    window.localStorage.getItem("openmates.demoMode") ===
      PRIVACY_VIDEO_DEMO_MODE
  );
}

export const privacyVideoDemoPrompt =
  "Draft an email to my landlord at schmidt.verwaltung@proton.com about the broken heater at Lindenstrasse 42, 10969 Berlin. Ask for a repair update and a callback at +49 171 000 9111. Sign it as clara.meyer@posteo.de.";

export const privacyVideoDemoSuggestions = [
  "[mail] Compare privacy focused email providers",
  "[ai] What is AES encryption and how does it work?",
  "[ai] Tips for protecting my privacy online?",
];

export const privacyVideoDemoChatTitle = "Landlord repair email";
export const privacyVideoDemoChatCategory = "general_knowledge";
export const privacyVideoDemoChatIcon = "help-circle";
export const privacyVideoDemoChatSummary =
  "George drafts a heater repair follow-up while keeping address, phone, and email private.";

export const privacyVideoDemoAssistantIntro =
  "I drafted the email and kept your private details protected.";

export const privacyVideoDemoAssistantResponse =
  `${privacyVideoDemoAssistantIntro}\n\n\`\`\`json\n{"type":"mail-email","embed_id":"privacy-video-mail-draft","status":"finished","receiver":"schmidt.verwaltung@proton.com","subject":"Repair update for the heater at Lindenstrasse 42","content":"Hello,\\n\\nI wanted to follow up about the broken heater at Lindenstrasse 42, 10969 Berlin. Could you please let me know when the repair is scheduled or send me an update on the next steps?\\n\\nYou can call me back at +49 171 000 9111.\\n\\nBest regards,\\nClara Meyer","footer":"clara.meyer@posteo.de"}\n\`\`\``;

export const privacyVideoDemoAssistantHiddenResponse =
  `${privacyVideoDemoAssistantIntro}\n\n\`\`\`json\n{"type":"mail-email","embed_id":"privacy-video-mail-draft","status":"finished","receiver":"[EMAIL_1_com]","subject":"Repair update for the heater at [ADDRESS_1]","content":"Hello,\\n\\nI wanted to follow up about the broken heater at [ADDRESS_1]. Could you please let me know when the repair is scheduled or send me an update on the next steps?\\n\\nYou can call me back at [PHONE_1_111].\\n\\nBest regards,\\nClara Meyer","footer":"[EMAIL_2_de]"}\n\`\`\``;
