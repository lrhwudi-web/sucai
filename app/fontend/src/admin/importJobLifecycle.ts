import type { ImportJob } from "./types";

export const IMPORT_COMPLETE_VISIBLE_MS = 5_000;

export function isImportJobTerminal(job: ImportJob) {
  return job.status === "completed" || job.status === "partial" || job.status === "failed";
}

export function isImportJobDismissible(job: ImportJob) {
  return job.status === "partial" || job.status === "failed";
}

export function isImportJobVisible(job: ImportJob, now = Date.now()) {
  if (job.status !== "completed") return true;
  if (job.finishedAt == null) return true;
  return now - job.finishedAt < IMPORT_COMPLETE_VISIBLE_MS;
}

export function nextCompletedImportJobExpiry(jobs: ImportJob[], now = Date.now()) {
  const remaining = jobs
    .filter((job) => job.status === "completed" && job.finishedAt != null)
    .map((job) => IMPORT_COMPLETE_VISIBLE_MS - (now - Number(job.finishedAt)))
    .filter((milliseconds) => milliseconds > 0);
  return remaining.length ? Math.min(...remaining) : null;
}
