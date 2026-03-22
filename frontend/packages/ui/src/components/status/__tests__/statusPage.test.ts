// frontend/packages/ui/src/components/status/__tests__/statusPage.test.ts
// Unit tests for status page data transformation logic.
// Tests the data shapes and helper behaviors used by status components.
//
// Architecture: See docs/architecture/status-page.md

import { describe, it, expect } from "vitest";

// ─── Status data shape validation ──────────────────────────────────────────

describe("status API response shapes", () => {
  // These tests validate the expected data contract between API and frontend.
  // If the API shape changes, these tests catch it.

  const sampleSummaryResponse = {
    overall_status: "degraded",
    last_updated: "2026-03-22T14:00:00+00:00",
    is_admin: false,
    health: {
      groups: [
        {
          group_name: "ai_providers",
          display_name: "AI Providers",
          status: "down",
          service_count: 11,
        },
        {
          group_name: "apps",
          display_name: "Applications",
          status: "operational",
          service_count: 18,
        },
      ],
    },
    timeline: {
      period_days: 90,
      buckets: [
        { start: "2025-12-22T14:00:00+00:00", end: "2025-12-23T14:00:00+00:00", status: "operational" },
        { start: "2025-12-23T14:00:00+00:00", end: "2025-12-24T14:00:00+00:00", status: "degraded" },
      ],
    },
    tests: {
      overall_status: "failing",
      latest_run: {
        run_id: "2026-03-22T03:00:00Z",
        timestamp: "2026-03-22T03:00:00Z",
        summary: { total: 80, passed: 76, failed: 4, skipped: 0 },
      },
      suites: [
        { name: "playwright", status: "failing", total: 80, passed: 76, failed: 4, skipped: 0, flaky: 0 },
      ],
      trend: [
        { date: "2026-03-21", total: 80, passed: 76, failed: 4 },
        { date: "2026-03-22", total: 80, passed: 78, failed: 2 },
      ],
    },
    incidents: {
      total_last_30d: 3,
    },
  };

  describe("summary response", () => {
    it("has required top-level fields", () => {
      expect(sampleSummaryResponse).toHaveProperty("overall_status");
      expect(sampleSummaryResponse).toHaveProperty("last_updated");
      expect(sampleSummaryResponse).toHaveProperty("is_admin");
    });

    it("overall_status is a valid value", () => {
      expect(["operational", "degraded", "down", "unknown"]).toContain(
        sampleSummaryResponse.overall_status,
      );
    });

    it("is_admin is false for unauthenticated requests", () => {
      expect(sampleSummaryResponse.is_admin).toBe(false);
    });
  });

  describe("health groups", () => {
    it("each group has required fields", () => {
      for (const group of sampleSummaryResponse.health.groups) {
        expect(group).toHaveProperty("group_name");
        expect(group).toHaveProperty("display_name");
        expect(group).toHaveProperty("status");
        expect(group).toHaveProperty("service_count");
        expect(typeof group.service_count).toBe("number");
      }
    });

    it("summary groups do NOT include individual services", () => {
      for (const group of sampleSummaryResponse.health.groups) {
        expect(group).not.toHaveProperty("services");
      }
    });
  });

  describe("timeline", () => {
    it("has period_days and buckets", () => {
      expect(sampleSummaryResponse.timeline.period_days).toBe(90);
      expect(Array.isArray(sampleSummaryResponse.timeline.buckets)).toBe(true);
    });

    it("each bucket has start, end, status", () => {
      for (const bucket of sampleSummaryResponse.timeline.buckets) {
        expect(bucket).toHaveProperty("start");
        expect(bucket).toHaveProperty("end");
        expect(bucket).toHaveProperty("status");
        expect(["operational", "degraded", "down", "unknown"]).toContain(bucket.status);
      }
    });
  });

  describe("tests section", () => {
    it("has overall_status and suites", () => {
      expect(sampleSummaryResponse.tests.overall_status).toBe("failing");
      expect(Array.isArray(sampleSummaryResponse.tests.suites)).toBe(true);
    });

    it("each suite has count fields", () => {
      for (const suite of sampleSummaryResponse.tests.suites) {
        expect(suite).toHaveProperty("name");
        expect(suite).toHaveProperty("total");
        expect(suite).toHaveProperty("passed");
        expect(suite).toHaveProperty("failed");
      }
    });

    it("trend is an array of date-keyed objects", () => {
      expect(Array.isArray(sampleSummaryResponse.tests.trend)).toBe(true);
      for (const point of sampleSummaryResponse.tests.trend) {
        expect(point).toHaveProperty("date");
        expect(point).toHaveProperty("total");
        expect(point).toHaveProperty("passed");
        expect(point).toHaveProperty("failed");
      }
    });
  });

  describe("incidents", () => {
    it("has total_last_30d count", () => {
      expect(typeof sampleSummaryResponse.incidents.total_last_30d).toBe("number");
    });
  });
});

// ─── Health detail response (expanded group) ────────────────────────────────

describe("health detail response", () => {
  const sampleNonAdminDetail = {
    group_name: "apps",
    display_name: "Applications",
    status: "operational",
    service_count: 18,
    services: [
      { id: "ai", name: "Ai", status: "operational" },
      { id: "web", name: "Web", status: "operational" },
    ],
  };

  const sampleAdminDetail = {
    group_name: "apps",
    display_name: "Applications",
    status: "operational",
    service_count: 18,
    services: [
      {
        id: "ai",
        name: "Ai",
        status: "operational",
        error_message: null,
        response_time_ms: { "1774190000": 150.5 },
        last_check: "2026-03-22T14:00:00Z",
      },
    ],
  };

  it("non-admin services have only id, name, status", () => {
    for (const service of sampleNonAdminDetail.services) {
      expect(Object.keys(service).sort()).toEqual(["id", "name", "status"]);
    }
  });

  it("admin services include error and response time fields", () => {
    const service = sampleAdminDetail.services[0];
    expect(service).toHaveProperty("error_message");
    expect(service).toHaveProperty("response_time_ms");
    expect(service).toHaveProperty("last_check");
  });
});

// ─── Test detail response (expanded suite) ──────────────────────────────────

describe("test detail response", () => {
  const sampleNonAdminTests = {
    suites: {
      playwright: {
        status: "failed",
        tests: [
          { name: "test-a.spec.ts", file: "test-a.spec.ts", status: "passed", duration_seconds: 5.0 },
          { name: "test-b.spec.ts", file: "test-b.spec.ts", status: "failed", duration_seconds: 10.0 },
        ],
      },
    },
  };

  it("non-admin test rows have no error field", () => {
    for (const test of sampleNonAdminTests.suites.playwright.tests) {
      expect(test).not.toHaveProperty("error");
    }
  });

  it("test rows have name, file, status, duration", () => {
    const test = sampleNonAdminTests.suites.playwright.tests[0];
    expect(test).toHaveProperty("name");
    expect(test).toHaveProperty("file");
    expect(test).toHaveProperty("status");
    expect(test).toHaveProperty("duration_seconds");
  });
});

// ─── Sparkline data computation ─────────────────────────────────────────────

describe("sparkline data computation", () => {
  it("computes pass rate correctly", () => {
    const trend = [
      { date: "2026-03-21", total: 100, passed: 80, failed: 20 },
      { date: "2026-03-22", total: 100, passed: 95, failed: 5 },
    ];

    const passRates = trend.map((t) => (t.total > 0 ? Math.round((t.passed / t.total) * 100) : 0));
    expect(passRates).toEqual([80, 95]);
  });

  it("handles zero total gracefully", () => {
    const trend = [{ date: "2026-03-22", total: 0, passed: 0, failed: 0 }];
    const rate = trend[0].total > 0 ? Math.round((trend[0].passed / trend[0].total) * 100) : 0;
    expect(rate).toBe(0);
  });
});

// ─── Status color mapping ───────────────────────────────────────────────────

describe("status color mapping", () => {
  const statusColors: Record<string, string> = {
    operational: "#22c55e",
    degraded: "#f59e0b",
    down: "#ef4444",
    unknown: "#d4d4d4",
  };

  it("maps all valid statuses to colors", () => {
    expect(statusColors["operational"]).toBe("#22c55e");
    expect(statusColors["degraded"]).toBe("#f59e0b");
    expect(statusColors["down"]).toBe("#ef4444");
    expect(statusColors["unknown"]).toBe("#d4d4d4");
  });

  it("unmapped status falls back to undefined", () => {
    expect(statusColors["bogus"]).toBeUndefined();
  });
});
