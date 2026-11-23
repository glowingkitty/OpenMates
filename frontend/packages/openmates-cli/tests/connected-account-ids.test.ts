// contract-test-file: supporting surface=cli assertions=connected-accounts.connection.private-reusable
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  connectedAccountMissingMessage,
  normalizeConnectedAccountAppId,
  normalizeConnectedAccountProviderId,
  resolveConnectedAccountAppId,
} from "../src/connectedAccountIds.ts";

describe("connected account id normalization", () => {
  // contract-test: supporting surface=cli assertions=connected-accounts.connection.private-reusable
  it("maps google_calendar to google and calendar", () => {
    assert.equal(normalizeConnectedAccountProviderId("google_calendar"), "google");
    assert.equal(normalizeConnectedAccountProviderId("revolut_business"), "revolut_business");
    assert.equal(normalizeConnectedAccountAppId("google_calendar"), "calendar");
  });

  // contract-test: supporting surface=cli assertions=connected-accounts.connection.private-reusable
  it("resolves legacy app_id and multi-app envelopes", () => {
    assert.equal(resolveConnectedAccountAppId({ app_id: "google_calendar" }, "calendar"), "calendar");
    assert.equal(resolveConnectedAccountAppId({ apps: { calendar: {}, mail: {} } }, "mail"), "mail");
    assert.notEqual(resolveConnectedAccountAppId({ apps: { calendar: {} } }, "mail"), "mail");
    assert.equal(resolveConnectedAccountAppId(null, "calendar"), "calendar");
  });

  // contract-test: supporting surface=cli assertions=connected-accounts.connection.private-reusable
  it("gives a provider-appropriate missing-account message", () => {
    assert.ok((connectedAccountMissingMessage("google")).includes("web app"));
    assert.ok(!(connectedAccountMissingMessage("google")).includes("revolut"));
    assert.ok((connectedAccountMissingMessage("revolut_business")).includes("connect-account revolut-business"));
  });
});
