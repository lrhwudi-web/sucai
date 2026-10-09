import type { MaterialAsset, MaterialProduct } from "../types";

export interface DownloadDirectory {
  name: string;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<DownloadDirectory>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<{
    createWritable(): Promise<{ write(chunk: Uint8Array): Promise<void>; close(): Promise<void>; abort(): Promise<void> }>;
  }>;
}

export type DownloadState = "queued" | "loading" | "downloading" | "ready" | "error" | "cancelled" | "manual";
export interface AssetDownloadJob {
  sku: string;
  name: string;
  state: DownloadState;
  completed: number;
  total: number;
  fileName: string;
  bytes: number;
  fileSize?: number;
  error: string;
  assets: MaterialAsset[];
  folderName: string;
}

export function safeDownloadName(value: string): string {
  const name = value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").trim();
  if (!name || name === "." || name === "..") return "asset";
  const safe = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name) ? `_${name}` : name;
  // Keep room for a collision suffix and preserve the extension.
  const dot = safe.lastIndexOf(".");
  const ext = dot > 0 && safe.length - dot <= 16 ? safe.slice(dot) : "";
  return safe.length > 160 ? safe.slice(0, 160 - ext.length) + ext : safe;
}

function suffixName(name: string, suffix: number) {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? `${name.slice(0, dot)} (${suffix})${name.slice(dot)}` : `${name} (${suffix})`;
}

function nestedFolders(asset: MaterialAsset, sku: string): string[] {
  const parts = (asset.path || "").split(/[\\/]/).filter(Boolean);
  const index = parts.findIndex((part) => part.startsWith(sku) && !/^\d/.test(part.slice(sku.length)));
  return index < 0 ? [] : parts.slice(index + 1, -1).map(safeDownloadName);
}

async function uniqueDirectory(root: DownloadDirectory, name: string) {
  for (let suffix = 0; suffix < 10000; suffix++) {
    const candidate = suffix ? `${name} (${suffix})` : name;
    try { await root.getDirectoryHandle(candidate); }
    catch (error) {
      if (error instanceof Error && error.name === "NotFoundError") {
        return root.getDirectoryHandle(candidate, { create: true });
      }
      throw error;
    }
  }
  throw new Error("Choose another destination folder.");
}

export const downloadIsActive = (job: AssetDownloadJob) => ["queued", "loading", "downloading"].includes(job.state);

/** Streams one file at a time per product; at most two products run concurrently. */
export class AssetDownloadQueue {
  private tasks = new Map<string, {
    job: AssetDownloadJob;
    root: DownloadDirectory | null;
    folder?: DownloadDirectory;
    paths: Map<string, string>;
    saved: Set<string>;
    controller: AbortController;
  }>();
  private active = 0;
  private listeners = new Set<(jobs: AssetDownloadJob[]) => void>();
  private version: AssetDownloadJob[] = [];

  constructor(private loadDetail: (sku: string, signal: AbortSignal) => Promise<MaterialProduct>, private request: typeof fetch = fetch) {}

  snapshot = () => this.version;
  subscribe = (listener: (jobs: AssetDownloadJob[]) => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private notify() {
    this.version = [...this.tasks.values()].map(({ job }) => ({ ...job }));
    this.listeners.forEach((listener) => listener(this.version));
  }
  add(products: MaterialProduct[], root: DownloadDirectory | null) {
    for (const product of products) {
      const existing = this.tasks.get(product.sku);
      // Every SKU keeps its own task. Repeated clicks never launch duplicate requests.
      if (existing) continue;
      this.tasks.set(product.sku, {
        job: { sku: product.sku, name: product.name, state: "queued", completed: 0, total: 0, fileName: "", bytes: 0, error: "", assets: [], folderName: "" },
        root, paths: new Map(), saved: new Set(), controller: new AbortController(),
      });
    }
    this.notify();
    this.pump();
  }
  retry(sku: string, root?: DownloadDirectory | null) {
    const task = this.tasks.get(sku);
    if (!task || !["error", "cancelled", "manual"].includes(task.job.state)) return;
    if (root !== undefined && root !== task.root) {
      // A new destination must include all files, including those saved in the old one.
      task.root = root; task.folder = undefined; task.saved.clear(); task.paths.clear();
    }
    task.controller = new AbortController();
    task.job.state = "queued"; task.job.error = "";
    this.notify(); this.pump();
  }
  cancel(sku: string) {
    const task = this.tasks.get(sku);
    if (!task || !downloadIsActive(task.job)) return;
    task.controller.abort();
    if (task.job.state === "queued") task.job.state = "cancelled";
    this.notify(); this.pump();
  }
  clear() {
    this.tasks.forEach((task) => task.controller.abort());
    this.tasks.clear(); this.notify();
  }
  remove(sku: string) {
    const task = this.tasks.get(sku);
    if (task && !downloadIsActive(task.job)) { this.tasks.delete(sku); this.notify(); }
  }
  private pump() {
    for (const task of this.tasks.values()) {
      if (this.active >= 2) break;
      if (task.job.state !== "queued") continue;
      task.job.state = "loading"; this.active++;
      void this.run(task).finally(() => { this.active--; this.notify(); this.pump(); });
    }
    this.notify();
  }
  private async run(task: NonNullable<ReturnType<AssetDownloadQueue["tasks"]["get"]>>) {
    const { job, controller } = task;
    const signal = controller.signal;
    try {
      const product = await this.loadDetail(job.sku, AbortSignal.any([signal, AbortSignal.timeout(30000)]));
      signal.throwIfAborted();
      job.assets = product.assets.filter((asset) => Boolean(asset.downloadUrl));
      job.total = job.assets.length; job.completed = task.saved.size;
      if (!job.total) throw new Error("No downloadable files are available for this product.");
      if (!task.root) { job.state = "manual"; this.notify(); return; }
      if (!task.folder) {
        task.folder = await uniqueDirectory(task.root, safeDownloadName(`${job.sku} ${job.name}`));
        job.folderName = task.folder.name;
      }
      for (const asset of job.assets) {
        signal.throwIfAborted();
        if (task.saved.has(asset.id)) continue;
        job.state = "downloading"; job.fileName = asset.name; job.bytes = 0; job.fileSize = asset.size;
        this.notify();
        let directory = task.folder;
        const folders = nestedFolders(asset, job.sku);
        for (const name of folders) directory = await directory.getDirectoryHandle(name, { create: true });
        let name = task.paths.get(asset.id);
        if (!name) {
          const base = safeDownloadName(asset.name);
          const used = new Set([...task.paths.entries()].map(([id, path]) => {
            const other = job.assets.find((item) => item.id === id);
            return `${nestedFolders(other || asset, job.sku).join("/")}/${path}`.toLowerCase();
          }));
          name = base;
          for (let suffix = 1; used.has(`${folders.join("/")}/${name}`.toLowerCase()); suffix++) name = suffixName(base, suffix);
          task.paths.set(asset.id, name);
        }
        await this.saveFile(asset, directory, name, signal, (bytes) => { job.bytes = bytes; this.notify(); });
        task.saved.add(asset.id); job.completed = task.saved.size;
        this.notify();
      }
      job.state = "ready"; job.fileName = "";
    } catch (error) {
      job.state = signal.aborted ? "cancelled" : "error";
      job.error = signal.aborted ? "" : error instanceof Error ? error.message : "Download failed. Please retry.";
    }
  }
  private async saveFile(asset: MaterialAsset, directory: DownloadDirectory, name: string, signal: AbortSignal, progress: (bytes: number) => void) {
    // Neither response.blob() nor arrayBuffer(): a large video never occupies its full size in memory.
    const transfer = new AbortController();
    const abort = () => transfer.abort(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const armTimeout = () => { timer = setTimeout(() => transfer.abort(new Error("No download data for 60 seconds. Please retry.")), 60000); };
    const disarmTimeout = () => { clearTimeout(timer); };
    armTimeout();
    try {
      const response = await this.request(asset.downloadUrl, { credentials: "include", redirect: "error", signal: transfer.signal });
      disarmTimeout();
      if (!response.ok) throw new Error(response.status === 401 ? "Your session has expired. Sign in, then retry." : `Could not download ${asset.name} (${response.status}).`);
      if (!response.body || response.headers.get("content-type")?.includes("text/html")) throw new Error("The server did not return a file. Sign in again, then retry.");
      const reader = response.body.getReader();
      let writable: Awaited<ReturnType<Awaited<ReturnType<DownloadDirectory["getFileHandle"]>>["createWritable"]>> | undefined;
      let closed = false;
      try {
        writable = await (await directory.getFileHandle(name, { create: true })).createWritable();
        let bytes = 0;
        let lastProgress = 0;
        for (;;) {
          signal.throwIfAborted();
          armTimeout();
          const { done, value } = await reader.read().finally(disarmTimeout);
          if (done) break;
          await writable.write(value);
          bytes += value.byteLength;
          if (Date.now() - lastProgress > 200) { progress(bytes); lastProgress = Date.now(); }
        }
        if (asset.size && bytes !== asset.size) throw new Error(`${asset.name} was incomplete or changed. Please retry.`);
        signal.throwIfAborted();
        await writable.close(); closed = true; progress(bytes);
      } finally {
        if (!closed && writable) await writable.abort().catch(() => undefined);
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    } finally {
      disarmTimeout();
      signal.removeEventListener("abort", abort);
    }
  }
}
