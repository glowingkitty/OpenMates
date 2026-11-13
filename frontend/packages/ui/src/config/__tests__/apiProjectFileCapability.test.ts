import { afterEach, describe, expect, it } from "vitest";

import {
  getWebSocketUrl,
  setChatMetadataRecoveryCapabilityEnabled,
  setProjectFileJobsCapabilityEnabled,
  setMemoryWriteJobsCapabilityEnabled,
  setRemoteCommandJobsCapabilityEnabled,
} from "../api";

describe("Project file WebSocket capability", () => {
  afterEach(() => {
    setProjectFileJobsCapabilityEnabled(false);
    setChatMetadataRecoveryCapabilityEnabled(false);
    setRemoteCommandJobsCapabilityEnabled(false);
    setMemoryWriteJobsCapabilityEnabled(false);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
  it("advertises assistant Memory write jobs only while the core job runner is installed", () => {
    expect(getWebSocketUrl()).not.toContain("memory_write_jobs");
    setMemoryWriteJobsCapabilityEnabled(true);
    expect(getWebSocketUrl()).toContain("memory_write_jobs");
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it("advertises sealed metadata recovery only after its handler is installed", () => {
    expect(getWebSocketUrl()).not.toContain("chat_metadata_recovery");
    setChatMetadataRecoveryCapabilityEnabled(true);
    expect(getWebSocketUrl()).toContain("chat_metadata_recovery");
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.executor-wait,projects.files.no-server-decryption-authority
  it("advertises Project file jobs only while a browser executor is installed", () => {
    expect(getWebSocketUrl("session", "token")).not.toContain(
      "client_capabilities=canonical_embed_receipts_v1,typed_recovery_outputs_v2,project_file_jobs",
    );

    setProjectFileJobsCapabilityEnabled(true);

    expect(getWebSocketUrl("session", "token")).toContain(
      "client_capabilities=canonical_embed_receipts_v1,typed_recovery_outputs_v2,project_file_jobs",
    );
  });

  // contract-test: supporting surface=gui.web assertions=code-run.remote.explicit-approval,code-run.execution.wait-or-continue
  it("advertises remote command jobs only while the origin client is installed", () => {
    expect(getWebSocketUrl()).not.toContain("remote_command_jobs");

    setProjectFileJobsCapabilityEnabled(true);
    setRemoteCommandJobsCapabilityEnabled(true);

    expect(getWebSocketUrl()).toContain(
      "client_capabilities=canonical_embed_receipts_v1,typed_recovery_outputs_v2,project_file_jobs,remote_command_jobs",
    );
  });
});
