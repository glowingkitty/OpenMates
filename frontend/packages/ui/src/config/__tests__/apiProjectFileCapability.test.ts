import { afterEach, describe, expect, it } from "vitest";

import {
  getWebSocketUrl,
  setProjectFileJobsCapabilityEnabled,
  setRemoteCommandJobsCapabilityEnabled,
} from "../api";

describe("Project file WebSocket capability", () => {
  afterEach(() => {
    setProjectFileJobsCapabilityEnabled(false);
    setRemoteCommandJobsCapabilityEnabled(false);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.executor-wait,projects.files.no-server-decryption-authority
  it("advertises Project file jobs only while a browser executor is installed", () => {
    expect(getWebSocketUrl("session", "token")).not.toContain(
      "client_capabilities=project_file_jobs",
    );

    setProjectFileJobsCapabilityEnabled(true);

    expect(getWebSocketUrl("session", "token")).toContain(
      "client_capabilities=project_file_jobs",
    );
  });

  // contract-test: supporting surface=gui.web assertions=code-run.remote.explicit-approval,code-run.execution.wait-or-continue
  it("advertises remote command jobs only while the origin client is installed", () => {
    expect(getWebSocketUrl()).not.toContain("remote_command_jobs");

    setProjectFileJobsCapabilityEnabled(true);
    setRemoteCommandJobsCapabilityEnabled(true);

    expect(getWebSocketUrl()).toContain(
      "client_capabilities=project_file_jobs,remote_command_jobs",
    );
  });
});
