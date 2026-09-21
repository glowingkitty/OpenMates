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
  title: "The confirmation page did not show what I submitted.",
  userFlow:
    "I opened Report Issue, completed each description field, and submitted the form.",
  expectedBehaviour:
    "The confirmation should summarize the report I just sent.",
  actualBehaviour: "Only the issue ID and a thank-you message were shown.",
});

export default {};
