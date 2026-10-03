import { runPrivacyDaemon } from "./privacyWorker.js";
void runPrivacyDaemon().catch(() => process.exit(1));
