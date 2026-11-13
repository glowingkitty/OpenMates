// OpenMates browser test recorder: Playwright reporter.
// Writes raw per-test events (steps with absolute times, attachment paths) to
// $OPENMATES_RECORDER_RAW. record_browser.py turns them into report.json.
const fs = require("fs");

const KEPT_CATEGORIES = new Set(["test.step", "expect", "pw:api"]);
const ANSI = /\u001b\[[0-9;]*m/g;

function clean(text) {
  return String(text || "").replace(ANSI, "").slice(0, 3900);
}

function flattenSteps(steps, depth, out) {
  for (const step of steps || []) {
    if (KEPT_CATEGORIES.has(step.category)) {
      out.push({
        title: String(step.title || ""),
        category: step.category,
        depth,
        startMs: step.startTime.getTime(),
        durationMs: Math.max(0, step.duration || 0),
        error: step.error ? clean(step.error.message) : null,
      });
    }
    flattenSteps(step.steps, depth + 1, out);
  }
}

function attachmentPath(result, name) {
  const found = (result.attachments || []).find((a) => a.name === name && a.path);
  return found ? found.path : null;
}

class OpenMatesRecorderReporter {
  constructor() {
    this.entries = new Map();
  }

  onTestEnd(test, result) {
    const steps = [];
    flattenSteps(result.steps, 0, steps);
    const titlePath = test.titlePath().slice(3).filter(Boolean);
    const outcome = result.status === "skipped" ? "skipped" : result.status === "passed" ? "passed" : "failed";
    // Retries overwrite: the last attempt is the one that counts.
    this.entries.set(test.id, {
      title: titlePath.join(" > ") || test.title,
      status: outcome,
      startMs: result.startTime.getTime(),
      durationMs: Math.max(0, result.duration || 0),
      error: result.error ? clean(result.error.message) : null,
      steps,
      video: attachmentPath(result, "video"),
      trace: attachmentPath(result, "trace"),
      screenshot: attachmentPath(result, "screenshot"),
    });
  }

  onEnd() {
    const target = process.env.OPENMATES_RECORDER_RAW;
    if (target) fs.writeFileSync(target, JSON.stringify({ tests: [...this.entries.values()] }));
  }

  printsToStdio() {
    return false;
  }
}

module.exports = OpenMatesRecorderReporter;
