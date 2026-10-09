import { useState } from "react";
import { CaretDown, DownloadSimple, X } from "@phosphor-icons/react";
import type { useAssetDownloads } from "../services/useAssetDownloads";
import { downloadIsActive } from "../services/assetDownloads";

export function DownloadPanel({ downloads }: { downloads: ReturnType<typeof useAssetDownloads> }) {
  const [collapsed, setCollapsed] = useState(false);
  if (!downloads.jobs.length) return null;
  const active = downloads.jobs.filter(downloadIsActive).length;
  const errors = downloads.jobs.filter((job) => job.state === "error").length;
  const ready = downloads.jobs.filter((job) => job.state === "ready").length;
  return <section className="download-panel" aria-label="Downloads">
    <button className="download-panel-heading" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}>
      <DownloadSimple size={20} weight="bold" /><strong>Downloads</strong>
      <span>{active ? `${active} active` : errors ? `${errors} need attention` : ready ? `${ready} saved` : "File links"}</span>
      <CaretDown size={18} style={{ transform: collapsed ? "rotate(180deg)" : undefined }} />
    </button>
    {!collapsed && <div className="download-panel-body">
      {!!downloads.jobs.length && <p className="download-destination">{downloads.folder ? `Saving to ${downloads.folder} · folders by product` : "Use the individual links below, or Download selected in desktop Edge / Chrome to save all files to a folder."}</p>}
      {downloads.jobs.map((job) => <article className="download-task" key={`file-${job.sku}`}>
        <div className="download-task-title"><strong>{job.sku}</strong><span>{job.state === "ready" ? "Saved" : job.state === "queued" ? "Queued" : job.state === "loading" ? "Loading files…" : job.state === "manual" ? `${job.total} file links` : job.state === "cancelled" ? "Stopped" : job.state === "error" ? "Needs retry" : `${job.completed} / ${job.total} saved`}</span>
          {!downloadIsActive(job) && <button aria-label={`Remove ${job.sku} download`} onClick={() => downloads.remove(job.sku)}><X size={15} /></button>}</div>
        <small>{job.name}</small>
        {job.state === "downloading" && <><progress max={job.total || 1} value={job.completed} aria-label={`${job.sku} files saved`} /><small>{job.fileName} · {(job.bytes / 1048576).toFixed(1)}{job.fileSize ? ` / ${(job.fileSize / 1048576).toFixed(1)}` : ""} MB</small></>}
        {job.state === "ready" && <small>{job.completed} files saved · {job.folderName}</small>}
        {job.error && <p className="download-error">{job.error}</p>}
        <div className="download-task-actions">
          {job.state === "manual" && <button onClick={() => void downloads.chooseAgain(job.sku)}>Save to folder</button>}
          {downloadIsActive(job) && <button onClick={() => downloads.cancel(job.sku)}>Stop</button>}
          {["error", "cancelled"].includes(job.state) && <><button onClick={() => downloads.retry(job.sku)}>Retry remaining files</button><button onClick={() => void downloads.chooseAgain(job.sku)}>Choose another folder</button></>}
        </div>
        {job.state === "manual" && <div className="download-file-links">{job.assets.map((asset) => <a key={asset.id} href={asset.downloadUrl} download={asset.name}><DownloadSimple size={14} />{asset.name}</a>)}</div>}
      </article>)}
    </div>}
  </section>;
}
