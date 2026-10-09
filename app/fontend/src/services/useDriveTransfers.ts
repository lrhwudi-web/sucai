import { useEffect, useRef, useState } from "react";
import { getProductDriveCopyStatus, prepareProductDriveCopy, SessionExpiredError } from "./materials";

export interface DriveTransfer {
  sku: string;
  state: "queued" | "building" | "ready" | "error";
  progress: number;
  folderUrl?: string;
  error?: string;
}

export function useDriveTransfers(account: number | undefined, onSessionExpired: () => void) {
  const [jobs, setJobs] = useState<DriveTransfer[]>([]);
  const tasks = useRef(new Map<string, DriveTransfer>());
  const chain = useRef(Promise.resolve());
  const epoch = useRef(0);
  const sessionExpired = useRef(onSessionExpired);
  sessionExpired.current = onSessionExpired;
  useEffect(() => {
    epoch.current++; tasks.current.clear(); setJobs([]); chain.current = Promise.resolve();
    return () => { epoch.current++; };
  }, [account]);
  const emit = () => setJobs([...tasks.current.values()].map((job) => ({ ...job })));
  const add = (sku: string) => {
    if (!account || tasks.current.has(sku)) return;
    const task: DriveTransfer = { sku, state: "queued", progress: 0 };
    const generation = epoch.current;
    tasks.current.set(sku, task); emit();
    chain.current = chain.current.then(async () => {
      if (generation !== epoch.current) return;
      const update = () => { if (generation === epoch.current) emit(); };
      try {
        task.state = "building"; update();
        let state = await prepareProductDriveCopy(sku);
        if (!state.job_id) throw new Error("The Drive preparation did not return a task ID.");
        let failures = 0;
        // Keep polling long-running copies; never discard a task after an arbitrary two minutes.
        while (generation === epoch.current && state.state !== "ready" && state.state !== "error") {
          task.progress = state.progress; update();
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
          if (generation !== epoch.current) return;
          try { state = await getProductDriveCopyStatus(sku, state.job_id!); failures = 0; }
          catch (error) {
            if (error instanceof SessionExpiredError || ++failures >= 5) throw error;
          }
        }
        if (generation !== epoch.current) return;
        if (state.state === "error") throw new Error(state.error || "The Drive folder could not be prepared.");
        if (!state.folder_url) throw new Error("The Drive folder link is missing.");
        task.state = "ready"; task.progress = 100; task.folderUrl = state.folder_url;
      } catch (error) {
        task.state = "error"; task.error = error instanceof Error ? error.message : "Drive preparation failed.";
        if (generation === epoch.current && error instanceof SessionExpiredError) sessionExpired.current();
      }
      update();
    });
  };
  const remove = (sku: string) => { const task = tasks.current.get(sku); if (task && ["ready", "error"].includes(task.state)) { tasks.current.delete(sku); emit(); } };
  const retry = (sku: string) => { remove(sku); add(sku); };
  return { jobs, add, remove, retry };
}
