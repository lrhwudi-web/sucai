import assert from "node:assert/strict";
import test from "node:test";
import {
  IMPORT_COMPLETE_VISIBLE_MS,
  isImportJobDismissible,
  isImportJobVisible,
  nextCompletedImportJobExpiry,
} from "../src/admin/importJobLifecycle.ts";

function job(status, finishedAt = null) {
  return {
    id: `${status}-job`,
    batchId: "batch",
    batchName: "Batch",
    status,
    progress: status === "completed" ? 100 : 50,
    total: 1,
    completed: status === "completed" ? 1 : 0,
    failed: status === "failed" || status === "partial" ? 1 : 0,
    createdBy: "Admin",
    createdAt: "now",
    finishedAt,
    dismissedAt: null,
    items: [],
  };
}

test("completed jobs stay visible for exactly five seconds", () => {
  const finishedAt = 1_000_000;
  const completed = job("completed", finishedAt);
  assert.equal(isImportJobVisible(completed, finishedAt + IMPORT_COMPLETE_VISIBLE_MS - 1), true);
  assert.equal(isImportJobVisible(completed, finishedAt + IMPORT_COMPLETE_VISIBLE_MS), false);
});

test("running and failed jobs remain visible", () => {
  assert.equal(isImportJobVisible(job("running"), Number.MAX_SAFE_INTEGER), true);
  assert.equal(isImportJobVisible(job("failed", 1), Number.MAX_SAFE_INTEGER), true);
  assert.equal(isImportJobVisible(job("partial", 1), Number.MAX_SAFE_INTEGER), true);
});

test("only failed and partial jobs can be manually closed", () => {
  assert.equal(isImportJobDismissible(job("failed")), true);
  assert.equal(isImportJobDismissible(job("partial")), true);
  assert.equal(isImportJobDismissible(job("running")), false);
  assert.equal(isImportJobDismissible(job("completed")), false);
});

test("the next expiry schedules the nearest completed job", () => {
  const now = 100_000;
  assert.equal(nextCompletedImportJobExpiry([job("completed", now - 2_000), job("completed", now - 4_000)], now), 1_000);
});
