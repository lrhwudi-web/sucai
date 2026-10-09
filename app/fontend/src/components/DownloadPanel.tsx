import { useState } from "react";
import { ArrowSquareOut, CaretDown, DownloadSimple, X } from "@phosphor-icons/react";
import type { useAssetDownloads } from "../services/useAssetDownloads";
import type { useDriveTransfers } from "../services/useDriveTransfers";
import { downloadIsActive } from "../services/assetDownloads";

export function DownloadPanel({ downloads, drive }: { downloads: ReturnType<typeof useAssetDownloads>; drive: ReturnType<typeof useDriveTransfers> }) {
  const [collapsed, setCollapsed] = useState(false);
  if (!downloads.jobs.length && !drive.jobs.length) return null;
  const active = downloads.jobs.filter(downloadIsActive).length + drive.jobs.filter((job) => ["queued", "building"].includes(job.state)).length;
  const errors = downloads.jobs.filter((job) => job.state === "error").length + drive.jobs.filter((job) => job.state === "error").length;
  const ready = downloads.jobs.filter((job) => job.state === "ready").length;
  return <section className="download-panel" aria-label="Downloads">
    <button className="download-panel-heading" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}>
      <DownloadSimple size={20} weight="bold" /><strong>Downloads</strong>
      <span>{active ? `${active} active` : errors ? `${errors} need attention` : ready ? `${ready} saved` : "Files & Drive links"}</span>
      <CaretDown size={18} style={{ transform: collapsed ? "rotate(180deg)" : undefined }} />
    </button>
    {!collapsed && <div className="download-panel-body">
      {!!downloads.jobs.length && <p className="download-destination">{downloads.folder ? `Saving to ${downloads.folder} · folders by product` : "Folder saving is unavailable here. Use the file links below, or open this site in desktop Edge / Chrome for batch saving."}</p>}
      {downloads.jobs.map((job) => <article className="download-task" key={`file-${job.sku}`}>
        <div className="download-task-title"><strong>{job.sku}</strong><span>{job.state === "ready" ? "Saved" : job.state === "queued" ? "Queued" : job.state === "loading" ? "Loading files…" : job.state === "manual" ? `${job.total} file links` : job.state === "cancelled" ? "Stopped" : job.state === "error" ? "Needs retry" : `${job.completed} / ${job.total} saved`}</span>
          {!downloadIsActive(job) && <button aria-label={`Remove ${job.sku} download`} onClick={() => downloads.remove(job.sku)}><X size={15} /></button>}</div>
        <small>{job.name}</small>
        {job.state === "downloading" && <><progress max={job.total || 1} value={job.completed} aria-label={`${job.sku} files saved`} /><small>{job.fileName} · {(job.bytes / 1048576).toFixed(1)}{job.fileSize ? ` / ${(job.fileSize / 1048576).toFixed(1)}` : ""} MB</small></>}
        {job.state === "ready" && <small>{job.completed} files saved · {job.folderName}</small>}
        {job.error && <p className="download-error">{job.error}</p>}
        <div className="download-task-actions">
          {downloadIsActive(job) && <button onClick={() => downloads.cancel(job.sku)}>Stop</button>}
          {["error", "cancelled"].includes(job.state) && <><button onClick={() => downloads.retry(job.sku)}>Retry remaining files</button><button onClick={() => void downloads.chooseAgain(job.sku)}>Choose another folder</button></>}
        </div>
        {job.state === "manual" && <div className="download-file-links">{job.assets.map((asset) => <a key={asset.id} href={asset.downloadUrl} download={asset.name}><DownloadSimple size={14} />{asset.name}</a>)}</div>}
      </article>)}
      {drive.jobs.map((job) => <article className="download-task" key={`drive-${job.sku}`}>
        <div className="download-task-title"><strong>{job.sku} · Drive</strong><span>{job.state === "queued" ? "Queued" : job.state === "building" ? `${job.progress}% prepared` : job.state === "ready" ? "Ready · 15 days" : "Needs retry"}</span>
          {["ready", "error"].includes(job.state) && <button aria-label={`Remove ${job.sku} Drive task`} onClick={() => drive.remove(job.sku)}><X size={15} /></button>}</div>
        {job.state === "building" && <progress max={100} value={job.progress} aria-label={`${job.sku} Drive preparation`} />}
        {job.folderUrl && <a className="download-drive-link" href={job.folderUrl} target="_blank" rel="noopener noreferrer"><ArrowSquareOut size={16} />Open {job.sku} in Drive</a>}
        {job.error && <><p className="download-error">{job.error}</p><button onClick={() => drive.retry(job.sku)}>Retry</button></>}
      </article>)}
    </div>}
  </section>;
}
