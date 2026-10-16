import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { shouldWaitForTeamAi, teamChatTitleFromMessage } from "../src/client.ts";

describe("Team chat AI trigger", () => {
  // contract-test: direct surface=cli assertions=teams.chat.encrypted-until-invoked
  it("accepts only OpenMates or a configured Mate wire mention", () => {
    assert.equal(shouldWaitForTeamAi("ordinary team discussion", "team-1"), false);
    assert.equal(shouldWaitForTeamAi("@OpenMates summarize", "team-1"), true);
    assert.equal(shouldWaitForTeamAi("@mate:software_development review", "team-1"), true);
    assert.equal(shouldWaitForTeamAi("@mate:unknown_person review", "team-1"), false);
    assert.equal(shouldWaitForTeamAi("@mate:onboarding_support review", "team-1"), false);
    assert.equal(shouldWaitForTeamAi("@Sophia review", "team-1"), false);
    assert.equal(shouldWaitForTeamAi("email@openmates.org", "team-1"), false);
    assert.equal(shouldWaitForTeamAi("@openmates_fake", "team-1"), false);
    assert.equal(shouldWaitForTeamAi("ordinary personal discussion", null), true);
  });

  // contract-test: direct surface=cli assertions=teams.chat.encrypted-until-invoked
  it("derives ordinary Team chat titles from the first human message", () => {
    assert.equal(teamChatTitleFromMessage("  Lunch   plan\nfor Friday  "), "Lunch plan for Friday");
    assert.equal(teamChatTitleFromMessage("🙂".repeat(90)), "🙂".repeat(80));
  });
});
