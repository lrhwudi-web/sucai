import { useState } from "react";
import { ArrowsClockwise, CheckCircle, Database, FileCsv, HardDrives, Scan, SpinnerGap, UploadSimple } from "@phosphor-icons/react";
import { postAdminAction, postAdminFile } from "./adminService";
import type { SyncStatus } from "./types";

interface SyncPanelProps {
  status: SyncStatus | null;
  onRefresh: () => Promise<void>;
  onNotify: (message: string) => void;
}

export function SyncPanel({ status, onRefresh, onNotify }: SyncPanelProps) {
  const [syncProgress, setSyncProgress] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const startSync = async () => {
    setSyncProgress(12);
    try {
      await postAdminAction("/admin/sync");
      setSyncProgress(100);
      await onRefresh();
      onNotify("Drive 索引同步完成");
    } catch (error) {
      setSyncProgress(null);
      throw error;
    }
  };
  const startScan = async () => {
    setScanning(true);
    try {
      await postAdminAction("/admin/nas-imports/scan");
      await onRefresh();
      onNotify("临时目录扫描完成");
    } finally {
      setScanning(false);
    }
  };
  const importCsv = async () => {
    if (!selectedFile) return;
    await postAdminFile("/admin/import-csv", selectedFile);
    await onRefresh();
    onNotify(`已导入 ${selectedFile.name}`);
    setSelectedFile(null);
  };

  return <section className="admin-section"><header className="admin-page-heading"><div><span className="eyebrow">Data operations</span><h1>同步与导入</h1><p>刷新 Drive 索引、扫描 NAS 临时目录，或导入产品 CSV 映射。</p></div></header>
    <div className="sync-grid">
      <article className="sync-card is-featured"><div className="sync-card-icon"><Database size={25} weight="duotone" /></div><div className="sync-card-heading"><div><span>Google Drive</span><h2>Drive 索引</h2></div><mark><i /> {status?.state === "error" ? "异常" : "已连接"}</mark></div><dl><div><dt>根目录</dt><dd>{status?.rootId || "未配置"}</dd></div><div><dt>已索引文件</dt><dd>{status?.fileCount ?? 0}</dd></div><div><dt>最近完成</dt><dd>{status?.finishedAt || "尚未同步"}</dd></div><div><dt>状态</dt><dd>{status?.state || "unknown"}</dd></div></dl>{syncProgress !== null && <div className="sync-progress"><span><b>{syncProgress}%</b>{syncProgress === 100 ? "同步完成" : "后端正在同步 Drive"}</span><div><i style={{ width: `${syncProgress}%` }} /></div></div>}<button className="button button-primary" onClick={startSync} disabled={syncProgress !== null && syncProgress < 100}>{syncProgress !== null && syncProgress < 100 ? <SpinnerGap className="is-spinning" size={18} weight="bold" /> : syncProgress === 100 ? <CheckCircle size={18} weight="bold" /> : <ArrowsClockwise size={18} weight="bold" />}{syncProgress !== null && syncProgress < 100 ? "正在同步" : "同步 Drive 索引"}</button></article>
      <article className="sync-card"><div className="sync-card-icon"><HardDrives size={25} weight="duotone" /></div><div className="sync-card-heading"><div><span>NAS inbox</span><h2>临时目录扫描</h2></div><mark><i /> 在线</mark></div><p>扫描 NAS 与 Drive“临时”目录，把新素材加入待确认队列，不会移动原文件。</p><div className="sync-note"><strong>后台状态</strong><span>{status?.message || "等待扫描"}</span></div><button className="button button-secondary" onClick={startScan} disabled={scanning}>{scanning ? <SpinnerGap className="is-spinning" size={18} weight="bold" /> : <Scan size={18} weight="bold" />}{scanning ? "正在扫描" : "扫描临时目录"}</button></article>
      <article className="sync-card"><div className="sync-card-icon"><FileCsv size={25} weight="duotone" /></div><div className="sync-card-heading"><div><span>Metadata</span><h2>CSV 映射导入</h2></div></div><p>导入 UTF-8 CSV，批量更新 SKU、英文品名、负责人和备注。</p><label className="csv-drop"><UploadSimple size={22} weight="duotone" /><strong>{selectedFile?.name || "选择 CSV 文件"}</strong><span>支持 .csv · 最大 10 MB</span><input type="file" accept=".csv" onChange={(event) => setSelectedFile(event.target.files?.[0] || null)} /></label><button className="button button-secondary" disabled={!selectedFile} onClick={importCsv}><UploadSimple size={18} weight="bold" /> 导入 CSV 映射</button></article>
    </div>
    <div className="admin-content-card sync-log"><div className="admin-card-heading"><div><ArrowsClockwise size={20} weight="duotone" /><span><strong>当前任务状态</strong><small>来自 FastAPI 同步状态表</small></span></div></div><div className="sync-log-row"><CheckCircle size={18} weight="fill" /><span><strong>Drive 索引</strong><small>{status?.message || "暂无同步信息"}</small></span><time>{status?.finishedAt || "—"}</time></div></div>
  </section>;
}
