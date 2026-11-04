/**
 * Fictional submitted-report data for the isolated confirmation preview.
 * The values are written to the same retained stores used by the real flow so
 * the component renders its standard post-submission state without an account.
 */
import {
  submittedIssueIdStore,
  submittedReportSummaryStore,
  submittedShortIssueIdStore,
} from "../../stores/reportIssueStore";

submittedIssueIdStore.set("00000000-0000-4000-8000-000000000001");
submittedShortIssueIdStore.set("V829F");
submittedReportSummaryStore.set({
  title:
    "I opened Report Issue and submitted it, but the confirmation page did not show what I wrote. I expected a summary of my report.",
});

export default {};
