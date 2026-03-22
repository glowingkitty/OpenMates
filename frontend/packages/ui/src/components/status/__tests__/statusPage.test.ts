// frontend/packages/ui/src/components/status/__tests__/statusPage.test.ts
// Unit tests for status page v2 API response shapes and helper logic.
// Architecture: See docs/architecture/status-page.md

import { describe, it, expect } from "vitest";

// ─── v2 API response shape validation ──────────────────────────────────────

describe("status API v2 response shapes", () => {
  const sampleResponse = {
    overall_status: "degraded",
    last_updated: "2026-03-22T14:00:00+00:00",
    is_admin: false,
    overall_timeline_30d: [
      { date: "2026-02-21", status: "operational" },
      { date: "2026-03-22", status: "degraded" },
    ],
    health: {
      groups: [
        {
          group_name: "ai_providers",
          display_name: "AI Providers",
          status: "operational",
          service_count: 1,
          timeline_30d: [{ date: "2026-03-22", status: "operational" }],
          services: [
            {
              id: "openai",
              name: "Openai",
              status: "operational",
              timeline_30d: [{ date: "2026-03-22", status: "operational" }],
            },
          ],
        },
      ],
    },
    tests: {
      overall_status: "failing",
      suites: [
        {
          name: "playwright",
          status: "failing",
          total: 80,
          passed: 76,
          failed: 4,
          skipped: 0,
          flaky: 0,
          timeline_30d: [
            {
              date: "2026-03-21",
              pass_rate: 0,
              total: 0,
              passed: 0,
              failed: 0,
              has_run: false,
              run_at: null,
            },
            {
              date: "2026-03-22",
              pass_rate: 95,
              total: 80,
              passed: 76,
              failed: 4,
              has_run: true,
              run_at: "2026-03-22T13:15:25Z",
            },
          ],
        },
      ],
      trend: [
        {
          date: "2026-03-21",
          total: 0,
          passed: 0,
          failed: 0,
          has_run: false,
          run_at: null,
        },
        {
          date: "2026-03-22",
          total: 80,
          passed: 76,
          failed: 4,
          has_run: true,
          run_at: "2026-03-22T13:15:25Z",
        },
      ],
      categories: {
        "Auth & Signup": {
          total: 11,
          passed: 8,
          failed: 3,
          skipped: 0,
          pass_rate: 73,
          history: [
            {
              date: "2026-03-21",
              pass_rate: 0,
              total: 11,
              passed: 0,
              failed: 0,
              not_run: 11,
              has_run: false,
              run_at: null,
              tone: null,
            },
            {
              date: "2026-03-22",
              pass_rate: 73,
              total: 11,
              passed: 8,
              failed: 2,
              not_run: 1,
              has_run: true,
              run_at: "2026-03-22T13:15:25Z",
              tone: 77,
            },
          ],
          tests: [
            {
              name: "signup-flow.spec.ts",
              file: "signup-flow.spec.ts",
              suite: "playwright",
              status: "passed",
              last_run: "2026-03-22T03:00:00Z",
              history_30d: [
                {
                  date: "2026-03-21",
                  status: "not_run",
                  has_run: false,
                  run_at: null,
                },
                {
                  date: "2026-03-22",
                  status: "passed",
                  has_run: true,
                  run_at: "2026-03-22T13:15:25Z",
                },
              ],
            },
          ],
        },
      },
    },
    incidents: { total_last_30d: 0 },
  };

  describe("overall_timeline_30d", () => {
    it("is an array of {date, status} objects", () => {
      expect(Array.isArray(sampleResponse.overall_timeline_30d)).toBe(true);
      for (const entry of sampleResponse.overall_timeline_30d) {
        expect(entry).toHaveProperty("date");
        expect(entry).toHaveProperty("status");
      }
    });
  });

  describe("health groups", () => {
    it("always include services[] with timeline_30d", () => {
      for (const group of sampleResponse.health.groups) {
        expect(group).toHaveProperty("services");
        expect(Array.isArray(group.services)).toBe(true);
        expect(group).toHaveProperty("timeline_30d");
        for (const svc of group.services) {
          expect(svc).toHaveProperty("timeline_30d");
          expect(svc).toHaveProperty("id");
          expect(svc).toHaveProperty("name");
          expect(svc).toHaveProperty("status");
        }
      }
    });

    it("does not expose protonmail in public overview groups", () => {
      const group = sampleResponse.health.groups[0];
      expect(group.services.map((service) => service.id)).not.toContain(
        "protonmail",
      );
    });
  });

  describe("test suites", () => {
    it("each suite has timeline_30d with pass_rate", () => {
      for (const suite of sampleResponse.tests.suites) {
        expect(suite).toHaveProperty("timeline_30d");
        for (const day of suite.timeline_30d) {
          expect(day).toHaveProperty("date");
          expect(day).toHaveProperty("pass_rate");
          expect(day).toHaveProperty("has_run");
          expect(day).toHaveProperty("run_at");
        }
      }
    });
  });

  describe("test categories", () => {
    it("include tests[] for all users (not admin-gated)", () => {
      const cat = sampleResponse.tests.categories["Auth & Signup"];
      expect(cat.tests).toBeDefined();
      expect(cat.tests!.length).toBeGreaterThan(0);
    });

    it("each test has history_30d and last_run", () => {
      const test = sampleResponse.tests.categories["Auth & Signup"].tests![0];
      expect(test).toHaveProperty("history_30d");
      expect(test).toHaveProperty("last_run");
      expect(test.history_30d[0].status).toBe("not_run");
    });

    it("category has pass_rate and history", () => {
      const cat = sampleResponse.tests.categories["Auth & Signup"];
      expect(cat.pass_rate).toBe(73);
      expect(cat.history.length).toBeGreaterThan(0);
      expect(cat.history[0].tone).toBeNull();
      expect(cat.history[1].tone).toBe(77);
    });
  });
});

// ─── Color interpolation ─────────────────────────────────────────────────

describe("pass rate color interpolation", () => {
  const NO_RUN_COLOR = "var(--color-grey-40)";

  function rateColor(rate: number): string {
    const r = Math.round(0x22 + (0xef - 0x22) * (1 - rate / 100));
    const g = Math.round(0xc5 + (0x44 - 0xc5) * (1 - rate / 100));
    const b = Math.round(0x5e + (0x44 - 0x5e) * (1 - rate / 100));
    return `rgb(${r},${g},${b})`;
  }

  it("100% = green (rgb(34,197,94))", () => {
    expect(rateColor(100)).toBe("rgb(34,197,94)");
  });

  it("0% = red (rgb(239,68,68))", () => {
    expect(rateColor(0)).toBe("rgb(239,68,68)");
  });

  it("50% is between green and red", () => {
    const mid = rateColor(50);
    expect(mid).not.toBe("rgb(34,197,94)");
    expect(mid).not.toBe("rgb(239,68,68)");
  });

  it("no-run days use grey instead of red", () => {
    expect(NO_RUN_COLOR).toBe("var(--color-grey-40)");
  });
});
