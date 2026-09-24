import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowCounterClockwise,
  Check,
  CheckCircle,
  CloudArrowUp,
  CaretLeft,
  CaretRight,
  Copy,
  DotsThree,
  Eye,
  Folders,
  MagnifyingGlass,
  Scan,
  SortAscending,
  SpinnerGap,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { defaultDriveFolderLeaves, expandFolderPaths } from "./DriveFolderPicker";
import { BatchFolderModal, ReviewModal } from "./ReviewModals";
import { loadImportJobs, mapImportJob, postAdminAction } from "./adminService";
import { isImportJobDismissible, isImportJobTerminal, isImportJobVisible, nextCompletedImportJobExpiry } from "./importJobLifecycle";
import { apiEnabled } from "../services/auth";
import type { CategoryOption, ImportJob, ImportStatus, ImportView, PendingImport, ThemeOption } from "./types";
import "./PendingReview.css";

interface PendingReviewProps {
  imports: PendingImport[];
  total: number;
  batchTotal: number;
  activeTotal: number;
  disabledTotal: number;
  view: ImportView;
  page: number;
  pageSize: number;
  pageCount: number;
  statusCounts: Record<ImportStatus, number>;
  loading: boolean;
  search: string;
  onViewChange: (view: ImportView) => void;
  onPageChange: (page: number) => void;
  onChange: (imports: PendingImport[]) => void;
  onRefresh: () => Promise<void>;
  onNotify: (message: string) => void;
  categoryOptions: CategoryOption[];
  themeOptions: ThemeOption[];
}

const ADMIN_PREVIEW_FALLBACK = "data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='126' height='110' viewBox='0 0 126 110'%3E%3Crect width='126' height='110' rx='10' fill='%23edf1ee'/%3E%3Cg fill='none' stroke='%236f8176' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='39' y='25' width='48' height='39' rx='5'/%3E%3Ccircle cx='52' cy='38' r='4'/%3E%3Cpath d='M43 57l16-16 11 11 8-8 12 14'/%3E%3C/g%3E%3Ctext x='63' y='84' text-anchor='middle' fill='%23526259' font-family='Arial,sans-serif' font-size='10'%3EOFFLINE%3C/text%3E%3C/svg%3E";

const importStageLabels: Record<string, string> = {
  queued: "等待入库",
  preparing: "准备目标目录",
  copying: "正在复制",
  moving: "正在移动",
  uploading: "正在上传",
  finalizing: "正在登记",
  completed: "入库完成",
  error: "入库失败",
};

function actionImportJob(result: Awaited<ReturnType<typeof postAdminAction>>): ImportJob | null {
  if (result.mode !== "api" || !result.data || typeof result.data !== "object") return null;
  const rawJob = (result.data as { job?: unknown }).job;
  return rawJob && typeof rawJob === "object" ? mapImportJob(rawJob as Record<string, unknown>) : null;
}

function ImportJobIndicator({ jobs, dismissing, onDismiss }: { jobs: ImportJob[]; dismissing?: boolean; onDismiss?: (job: ImportJob) => void }) {
  const job = jobs.find((candidate) => candidate.status === "running" || candidate.status === "queued") || jobs[0];
  if (!job) return null;
  const hasError = job.status === "failed" || job.status === "partial";
  const complete = job.status === "completed";
  return (
    <span
      className={`pending-import-job-indicator ${complete ? "is-complete" : ""} ${hasError ? "has-error" : ""}`}
      aria-label={`${job.batchName} 入库进度 ${job.progress}%`}
    >
      {hasError
        ? <WarningCircle size={17} weight="fill" />
        : complete
          ? <CheckCircle size={17} weight="fill" />
          : <CloudArrowUp size={17} weight="bold" />}
      <b>{job.progress}%</b>
      {hasError && onDismiss && (
        <button
          className="pending-import-job-dismiss"
          type="button"
          disabled={dismissing}
          onClick={(event) => { event.stopPropagation(); onDismiss(job); }}
          aria-label={`关闭 ${job.batchName} 的异常入库任务`}
          title="关闭异常任务"
        >
          <X size={12} weight="bold" />
        </button>
      )}
      <span className="pending-import-job-tooltip" role="tooltip">
        <strong>{job.batchName}</strong>
        <small>总进度 {job.progress}% · {job.completed}/{job.total} 完成{job.failed ? ` · ${job.failed} 失败` : ""}</small>
        <span className="pending-import-job-items">
          {job.items.map((item) => (
            <span className={`pending-import-job-item is-${item.status}`} key={item.importId}>
              <span><em>{item.name}</em><b>{item.progress}%</b></span>
              <i><u style={{ width: `${item.progress}%` }} /></i>
              <small>{item.error || importStageLabels[item.stage] || item.stage}</small>
            </span>
          ))}
        </span>
      </span>
    </span>
  );
}

const statusLabel: Record<ImportStatus, string> = {
  pending: "待建议",
  suggested: "待确认",
  error: "需处理",
  rejected: "暂时弃用",
};

function categoryRequired(item: PendingImport) {
  return item.driveFolder.startsWith("04 Product Images");
}

function itemReady(item: PendingImport) {
  return Boolean(
    item.sku
    && item.englishName
    && item.driveFolder
    && item.driveName
    && (!categoryRequired(item) || item.categoryId),
  );
}

function savePayload(item: PendingImport) {
  return {
    final_sku: item.sku,
    final_english_name: item.englishName,
    final_drive_folder: item.driveFolder,
    final_drive_name: item.driveName,
    final_asset_type: item.assetType,
    final_set_code: item.setCode,
    final_category_id: item.categoryId,
    final_category_tags: item.categoryTags.join("|"),
    final_themes: item.themes.join("|"),
    update_themes: true,
    expected_revision: item.revision,
  };
}

export function PendingReview({ imports, total, batchTotal, activeTotal, disabledTotal, view, page, pageSize, pageCount, statusCounts, loading, search, onViewChange, onPageChange, onChange, onRefresh, onNotify, categoryOptions, themeOptions }: PendingReviewProps) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [queueSearch, setQueueSearch] = useState("");
  const [batchSort, setBatchSort] = useState<"newest" | "oldest">("newest");
  const [scanning, setScanning] = useState(false);
  const [activeItemId, setActiveItemId] = useState<number | null>(null);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [batchMenuOpen, setBatchMenuOpen] = useState(false);
  const [importJobs, setImportJobs] = useState<ImportJob[]>([]);
  const [dismissingJobId, setDismissingJobId] = useState<string | null>(null);
  const [jobClock, setJobClock] = useState(() => Date.now());
  const knownTerminalJobs = useRef<Set<string>>(new Set());
  const [folderPaths, setFolderPaths] = useState(() => apiEnabled()
    ? []
    : expandFolderPaths([...defaultDriveFolderLeaves, ...imports.map((item) => item.driveFolder).filter(Boolean)]));

  useEffect(() => {
    if (apiEnabled()) return;
    setFolderPaths((current) => expandFolderPaths([...current, ...imports.map((item) => item.driveFolder).filter(Boolean)]));
  }, [imports]);

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const jobs = await loadImportJobs();
        if (disposed) return;
        const newlyTerminal = jobs.filter((job) => isImportJobTerminal(job) && !knownTerminalJobs.current.has(job.id));
        jobs.filter(isImportJobTerminal).forEach((job) => knownTerminalJobs.current.add(job.id));
        setImportJobs(jobs);
        setJobClock(Date.now());
        if (newlyTerminal.length) void onRefresh().catch(() => undefined);
      } catch {
        // The pending queue remains usable if a transient progress poll fails.
      }
    };
    void refresh();
    if (!apiEnabled()) {
      return () => { disposed = true; };
    }
    const timer = window.setInterval(refresh, 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [onRefresh]);

  useEffect(() => {
    const remaining = nextCompletedImportJobExpiry(importJobs);
    if (remaining == null) return;
    const timer = window.setTimeout(() => setJobClock(Date.now()), remaining + 25);
    return () => window.clearTimeout(timer);
  }, [importJobs, jobClock]);

  useEffect(() => {
    setChecked(new Set());
    setActiveItemId(null);
    setActiveBatchId(null);
    setSelectedBatchId(null);
    setBatchMenuOpen(false);
  }, [page, view]);

  const filtered = useMemo(() => {
    const needle = `${search} ${queueSearch}`.trim().toLowerCase();
    if (!needle) return imports;
    return imports.filter((item) => [item.name, item.relPath, item.batchName, item.sku, item.englishName, item.driveFolder, statusLabel[item.status]]
      .join(" ").toLowerCase().includes(needle));
  }, [imports, queueSearch, search]);

  const visibleBatches = useMemo(() => {
    const groups = new Map<string, { id: string; name: string; items: PendingImport[] }>();
    filtered.forEach((item) => {
      const group = groups.get(item.batchId) || { id: item.batchId, name: item.batchName, items: [] };
      group.items.push(item);
      groups.set(item.batchId, group);
    });
    return [...groups.values()].sort((a, b) => {
      const aTime = a.items[0]?.discoveredAt || "";
      const bTime = b.items[0]?.discoveredAt || "";
      return batchSort === "newest" ? bTime.localeCompare(aTime) : aTime.localeCompare(bTime);
    });
  }, [batchSort, filtered]);

  const visibleImportJobs = useMemo(
    () => importJobs.filter((job) => isImportJobVisible(job, jobClock)),
    [importJobs, jobClock],
  );

  const jobsByBatch = useMemo(() => {
    const groups = new Map<string, ImportJob[]>();
    visibleImportJobs.forEach((job) => groups.set(job.batchId, [...(groups.get(job.batchId) || []), job]));
    return groups;
  }, [visibleImportJobs]);

  const orphanJobs = useMemo(() => {
    const visibleIds = new Set(visibleBatches.map((batch) => batch.id));
    return visibleImportJobs.filter((job) => !visibleIds.has(job.batchId));
  }, [visibleImportJobs, visibleBatches]);

  useEffect(() => {
    if (!visibleBatches.length) {
      setSelectedBatchId(null);
      return;
    }
    if (!selectedBatchId || !visibleBatches.some((batch) => batch.id === selectedBatchId)) {
      setSelectedBatchId(visibleBatches[0].id);
    }
  }, [selectedBatchId, visibleBatches]);

  const isDisabledView = view === "disabled";
  const activeItem = imports.find((item) => item.id === activeItemId) || null;
  const activeBatchItems = imports.filter((item) => item.batchId === activeBatchId);
  const activeBatchName = activeBatchItems[0]?.batchName || "";
  const selectedBatch = visibleBatches.find((batch) => batch.id === selectedBatchId) || null;
  const selectedBatchItems = selectedBatch
    ? imports.filter((item) => item.batchId === selectedBatch.id)
    : [];
  const selectedBatchVisibleItems = selectedBatch?.items || [];
  const selectedBatchPath = selectedBatchItems[0]?.relPath.split("/").slice(0, -1).join("/") || selectedBatch?.id || "";
  const selectedTargetFolder = selectedBatchItems.find((item) => item.driveFolder)?.driveFolder || "";

  const toggleChecked = (id: number) => {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const suggestItem = (item: PendingImport): PendingImport => ({
    ...item,
    status: "suggested",
    confidence: item.confidence || 0.86,
    reason: item.reason === "尚未生成建议。" ? "已根据文件名、同批素材与现有 Drive 目录生成建议。" : item.reason,
    error: undefined,
    sku: item.sku || (item.batchId === "B-20260715-01" ? "6012318" : item.name.includes("T36") ? "EVT-T36" : "6012240"),
    englishName: item.englishName || (item.batchId === "B-20260715-01" ? "Tailored Monkey Driver Headcover" : item.name.includes("T36") ? "Thailand Golf Expo 2026" : "Happy Taco Putter Collection"),
    driveFolder: item.driveFolder || (item.batchId === "B-20260715-01" ? "04 Product Images/Craftsman Golf/Driver Headcovers/6012318" : item.name.includes("T36") ? "06 Show & Exhibitions/Thailand Golf Expo 2026" : "04 Product Images/Big Crazy/Putter Covers/6012240"),
    driveName: item.driveName.toLowerCase().replaceAll("_", "-"),
    categoryId: item.categoryId || (item.batchId === "B-20260715-01" ? "HC_DRIVER" : ""),
    categoryTags: item.categoryTags,
    categoryConfidence: item.categoryConfidence || 0.9,
    categorySource: item.categorySource || "deterministic_rule",
    categoryReason: item.categoryReason || "已根据固定分类词典生成建议。",
    categoryNeedsReview: item.batchId !== "B-20260715-01",
  });

  const runSuggestion = async (ids: number[]) => {
    if (!ids.length) return;
    const result = await postAdminAction(ids.length === 1 ? `/admin/nas-imports/${ids[0]}/suggest` : "/admin/nas-imports/bulk", ids.length === 1 ? {} : { import_ids: ids, action: "suggest" });
    if (result.mode === "api") await onRefresh();
    else onChange(imports.map((item) => ids.includes(item.id) ? suggestItem(item) : item));
    onNotify(`已为 ${ids.length} 条素材生成建议`);
  };

  const saveItem = async (draft: PendingImport) => {
    const result = await postAdminAction(`/admin/nas-imports/${draft.id}/save`, savePayload(draft));
    if (result.mode === "api") await onRefresh();
    else onChange(imports.map((item) => item.id === draft.id ? draft : item));
    onNotify("修改已保存");
  };

  const saveItems = async (drafts: PendingImport[]) => {
    if (!drafts.length) return;
    const result = await postAdminAction("/admin/nas-imports/bulk-identity", {
      import_ids: drafts.map((draft) => draft.id),
      final_sku: drafts[0].sku,
      final_english_name: drafts[0].englishName,
      final_drive_names: drafts.map((draft) => draft.driveName),
      expected_revisions: drafts.map((draft) => draft.revision),
    });
    if (result.mode === "api") {
      await onRefresh();
    } else {
      const draftsById = new Map(drafts.map((draft) => [draft.id, draft]));
      onChange(imports.map((item) => draftsById.get(item.id) || item));
    }
    onNotify(`修改已应用到本批 ${drafts.length} 条素材`);
  };

  const rejectItem = async (draft: PendingImport) => {
    const result = await postAdminAction(`/admin/nas-imports/${draft.id}/reject`);
    if (result.mode === "api") await onRefresh();
    else onChange(imports.filter((item) => item.id !== draft.id));
    setChecked((current) => { const next = new Set(current); next.delete(draft.id); return next; });
    onNotify("素材已移入暂时弃用，可随时恢复");
  };

  const rejectItems = async (ids: number[]) => {
    const targetIds = ids.filter((id) => imports.some((item) => item.id === id));
    if (!targetIds.length) return;
    const result = await postAdminAction("/admin/nas-imports/bulk", { import_ids: targetIds, action: "reject" });
    if (result.mode === "api") await onRefresh();
    else onChange(imports.filter((item) => !targetIds.includes(item.id)));
    setChecked(new Set());
    onNotify(`已将 ${targetIds.length} 条素材移入暂时弃用`);
  };

  const restoreItems = async (ids: number[]) => {
    const targetIds = ids.filter((id) => imports.some((item) => item.id === id));
    if (!targetIds.length) return;
    const result = await postAdminAction("/admin/nas-imports/bulk", { import_ids: targetIds, action: "restore" });
    if (result.mode === "api") await onRefresh();
    else onChange(imports.filter((item) => !targetIds.includes(item.id)));
    setChecked(new Set());
    onNotify(`已恢复 ${targetIds.length} 条素材，可重新审核并入库`);
  };

  const approveItem = async (draft: PendingImport) => {
    const result = await postAdminAction(`/admin/nas-imports/${draft.id}/approve`, {
      ...savePayload(draft),
      batch_id: draft.batchId,
      batch_name: draft.batchName,
    });
    const queuedJob = actionImportJob(result);
    if (queuedJob) setImportJobs((current) => [queuedJob, ...current.filter((job) => job.id !== queuedJob.id)]);
    onChange(imports.filter((item) => item.id !== draft.id));
    if (result.mode === "api") void onRefresh().catch(() => undefined);
    setChecked((current) => { const next = new Set(current); next.delete(draft.id); return next; });
    onNotify("素材已加入后台入库，可以继续审核下一条");
  };

  const applyBatchSettings = async (batchId: string, folder: string, setCode: string, categoryId: string, themes: string[], updateThemes: boolean, approve: boolean) => {
    const applySettings = (item: PendingImport) => ({
      ...item,
      driveFolder: folder || item.driveFolder,
      setCode: setCode || item.setCode,
      categoryId: categoryId || item.categoryId,
      themes: updateThemes ? themes : item.themes,
      categoryNeedsReview: categoryId ? false : item.categoryNeedsReview,
    });
    const batchItems = imports.filter((item) => item.batchId === batchId).map(applySettings);
    const nextImports = imports.map((item) => item.batchId === batchId ? applySettings(item) : item);
    const batchName = batchItems[0]?.batchName || "当前批次";
    if (approve) {
      setActiveBatchId(null);
    }

    try {
      const settingsResult = await postAdminAction("/admin/nas-imports/bulk-settings", {
        import_ids: batchItems.map((item) => item.id),
        final_drive_folder: folder,
        final_set_code: setCode,
        final_category_id: categoryId,
        final_themes: themes.join("|"),
        update_themes: updateThemes,
        expected_revisions: batchItems.map((item) => item.revision),
      });
      if (approve) {
        const result = await postAdminAction("/admin/nas-imports/bulk", {
          import_ids: batchItems.map((item) => item.id),
          action: "approve",
          batch_id: batchId,
          batch_name: batchName,
        });
        const queuedJob = actionImportJob(result);
        if (queuedJob) setImportJobs((current) => [queuedJob, ...current.filter((job) => job.id !== queuedJob.id)]);
        onChange(nextImports.filter((item) => item.batchId !== batchId));
        if (result.mode === "api") void onRefresh().catch(() => undefined);
        setChecked(new Set());
        onNotify(`“${batchName}”的 ${batchItems.length} 个素材已转入后台入库，可以继续审核下一批`);
        return;
      }
      if (settingsResult.mode === "api") await onRefresh();
      else onChange(nextImports);
      onNotify(`目录、分类与主题设置已应用到本批 ${batchItems.length} 条素材`);
    } catch (error) {
      if (!approve) throw error;
      const message = error instanceof Error ? error.message : "未知错误";
      try {
        await onRefresh();
      } catch {
        // The original operation error is more useful to the administrator.
      }
      onNotify(`“${batchName}”整批入库失败：${message}`);
    }
  };

  const scan = async () => {
    setScanning(true);
    try {
      const result = await postAdminAction("/admin/nas-imports/scan");
      if (result.mode === "api") await onRefresh();
      onNotify("扫描完成，临时目录没有遗漏文件");
    } finally {
      setScanning(false);
    }
  };

  const copyBatchPath = async () => {
    if (!selectedBatchPath) return;
    try {
      await navigator.clipboard.writeText(selectedBatchPath);
      onNotify("上传路径已复制");
    } catch {
      onNotify("无法自动复制，请从批次详情中复制路径");
    }
    setBatchMenuOpen(false);
  };

  const dismissImportJob = async (job: ImportJob) => {
    if (!isImportJobDismissible(job) || dismissingJobId) return;
    setDismissingJobId(job.id);
    try {
      const result = await postAdminAction(`/api/admin/import-jobs/${encodeURIComponent(job.id)}/dismiss`);
      setImportJobs((current) => current.filter((candidate) => candidate.id !== job.id));
      if (result.mode === "api") void onRefresh().catch(() => undefined);
      onNotify(`已关闭“${job.batchName}”的异常入库任务；已成功素材仍保留在入库记录中`);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "关闭异常入库任务失败");
    } finally {
      setDismissingJobId(null);
    }
  };

  const selectedVisibleIds = selectedBatchVisibleItems.map((item) => item.id);
  const selectedBatchAllChecked = Boolean(selectedVisibleIds.length)
    && selectedVisibleIds.every((id) => checked.has(id));

  return (
    <section className="admin-section pending-review-section">
      {!apiEnabled() && (
        <div className="pending-demo-notice" role="status">
          <CheckCircle size={18} weight="fill" />
          <strong>本地模拟模式</strong>
          <span>所有入库操作只更新当前页面，不会连接服务器、Google Drive 或数据库。</span>
        </div>
      )}
      <section className="pending-workspace-shell">
        <header className="pending-workspace-toolbar">
          <nav className="review-view-tabs pending-view-tabs" aria-label="待确认素材视图">
            <button type="button" className={!isDisabledView ? "is-active" : ""} onClick={() => onViewChange("active")} aria-current={!isDisabledView ? "page" : undefined} title={`待生成建议 ${statusCounts.pending}，待确认 ${statusCounts.suggested}，需处理 ${statusCounts.error}`}>
              待确认 <span>{activeTotal}</span>
            </button>
            <button type="button" className={isDisabledView ? "is-active" : ""} onClick={() => onViewChange("disabled")} aria-current={isDisabledView ? "page" : undefined}>
              暂时弃用 <span>{disabledTotal}</span>
            </button>
          </nav>
          <label className="admin-search-field pending-search-field">
            <MagnifyingGlass size={18} weight="bold" />
            <input value={queueSearch} onChange={(event) => setQueueSearch(event.target.value)} placeholder="搜索批次、文件、SKU 或路径" />
          </label>
          <button className="pending-scan-button" onClick={scan} disabled={scanning}>
            {scanning ? <SpinnerGap className="is-spinning" size={17} weight="bold" /> : <Scan size={17} weight="bold" />}
            {scanning ? "正在扫描" : "扫描临时目录"}
          </button>
        </header>

        <div className="pending-split-workspace">
          <aside className="pending-batch-pane" aria-label="上传批次">
            <div className="pending-batch-sort">
              <SortAscending size={17} weight="bold" />
              <select value={batchSort} onChange={(event) => setBatchSort(event.target.value as "newest" | "oldest")} aria-label="批次排序">
                <option value="newest">按上传时间排序</option>
                <option value="oldest">最早上传优先</option>
              </select>
            </div>
            <div className="pending-batch-list">
              {orphanJobs.map((job) => (
                <article className={`pending-batch-card is-import-job ${isImportJobDismissible(job) ? "has-error" : ""}`} key={job.id}>
                  <span className="pending-batch-card-title">
                    <i />
                    <strong>{job.batchName}</strong>
                    <span className="pending-batch-card-actions">
                      <em>{job.total} 个素材</em>
                      <ImportJobIndicator jobs={[job]} dismissing={dismissingJobId === job.id} onDismiss={dismissImportJob} />
                    </span>
                  </span>
                  <time>{job.createdAt}</time>
                  <small>{job.status === "completed" ? "后台入库已完成，5 秒后自动收起" : job.status === "failed" ? "后台入库失败，请处理后重试或手动关闭" : job.status === "partial" ? "后台入库部分失败，请处理后重试或手动关闭" : "后台入库中，可继续审核其他批次"}</small>
                </article>
              ))}
              {visibleBatches.map((batch) => {
                const batchItems = imports.filter((item) => item.batchId === batch.id);
                const batchPath = batchItems[0]?.relPath.split("/").slice(0, -1).join("/") || batch.id;
                const batchJobs = jobsByBatch.get(batch.id) || [];
                const dismissibleBatchJob = batchJobs.find(isImportJobDismissible);
                return (
                  <article
                    role="button"
                    tabIndex={0}
                    className={`pending-batch-card ${selectedBatchId === batch.id ? "is-selected" : ""}`}
                    key={batch.id}
                    onClick={() => { setSelectedBatchId(batch.id); setBatchMenuOpen(false); }}
                    onKeyDown={(event) => {
                      if (event.target !== event.currentTarget || (event.key !== "Enter" && event.key !== " ")) return;
                      event.preventDefault();
                      setSelectedBatchId(batch.id);
                      setBatchMenuOpen(false);
                    }}
                    aria-pressed={selectedBatchId === batch.id}
                  >
                    <span className="pending-batch-card-title">
                      <i />
                      <strong>{batch.name}</strong>
                      <span className="pending-batch-card-actions">
                        <em>{batchItems.length} 个素材</em>
                        <ImportJobIndicator jobs={batchJobs} dismissing={dismissingJobId === dismissibleBatchJob?.id} onDismiss={dismissImportJob} />
                      </span>
                    </span>
                    <time>{batchItems[0]?.discoveredAt || "—"}</time>
                    <small>/{batchPath}/</small>
                  </article>
                );
              })}
              {!visibleBatches.length && !orphanJobs.length && (
                <div className="pending-batch-empty">
                  {isDisabledView ? <Archive size={28} weight="duotone" /> : <CheckCircle size={28} weight="duotone" />}
                  <strong>{isDisabledView ? "没有暂时弃用批次" : "没有匹配的批次"}</strong>
                  <span>调整搜索关键词后再试。</span>
                </div>
              )}
            </div>
          </aside>

          <section className="pending-detail-pane" aria-live="polite">
            {selectedBatch ? (
              <>
                <header className="pending-batch-detail-header">
                  <div className="pending-batch-detail-copy">
                    <div className="pending-batch-heading-line">
                      <h2>{selectedBatch.name}</h2>
                      <span className={`admin-status ${selectedBatchItems[0]?.status || "pending"}`}>
                        <i />
                        {isDisabledView ? "暂时弃用" : "待确认"}
                      </span>
                    </div>
                    <div className="pending-batch-meta">
                      <span>上传时间：<strong>{selectedBatchItems[0]?.discoveredAt || "—"}</strong></span>
                      <span>素材数量：<strong>{selectedBatchItems.length}</strong></span>
                      <span>上传路径：<strong>/{selectedBatchPath}/</strong></span>
                    </div>
                    <p>建议目标目录：<strong>{selectedTargetFolder ? `/${selectedTargetFolder}/` : "等待生成或核对目录"}</strong></p>
                  </div>
                  <div className="pending-batch-menu">
                    <button type="button" className="pending-kebab-button" onClick={() => setBatchMenuOpen((current) => !current)} aria-label="打开批次操作" aria-expanded={batchMenuOpen}>
                      <DotsThree size={21} weight="bold" />
                    </button>
                    {batchMenuOpen && (
                      <div className="pending-batch-menu-popover">
                        {!isDisabledView && <button type="button" onClick={() => { setActiveBatchId(selectedBatch.id); setBatchMenuOpen(false); }}><Folders size={16} weight="bold" /> 开始整批审批</button>}
                        <button type="button" onClick={copyBatchPath}><Copy size={16} weight="bold" /> 复制上传路径</button>
                        {isDisabledView
                          ? <button type="button" onClick={() => { restoreItems(selectedBatchItems.map((item) => item.id)); setBatchMenuOpen(false); }}><ArrowCounterClockwise size={16} weight="bold" /> 恢复整个批次</button>
                          : <button type="button" className="is-danger" onClick={() => { rejectItems(selectedBatchItems.map((item) => item.id)); setBatchMenuOpen(false); }}><Archive size={16} weight="bold" /> 暂时弃用批次</button>}
                      </div>
                    )}
                  </div>
                </header>

                <div className="pending-file-table" role="table" aria-label={`${selectedBatch.name} 素材`}>
                  <div className="pending-file-table-head" role="row">
                    <span role="columnheader">
                      <label className="admin-check">
                        <input
                          type="checkbox"
                          aria-label="全选当前批次素材"
                          checked={selectedBatchAllChecked}
                          onChange={() => {
                            setChecked((current) => {
                              const next = new Set(current);
                              if (selectedBatchAllChecked) selectedVisibleIds.forEach((id) => next.delete(id));
                              else selectedVisibleIds.forEach((id) => next.add(id));
                              return next;
                            });
                          }}
                        />
                        <span><Check size={13} weight="bold" /></span>
                      </label>
                      素材文件
                    </span>
                    <span role="columnheader">SKU 状态</span>
                    <span role="columnheader">建议分类/目标目录</span>
                    <span role="columnheader">操作</span>
                  </div>

                  <div className="pending-file-table-body">
                    {selectedBatchVisibleItems.map((item) => (
                      <article className="pending-file-row" role="row" key={item.id}>
                        <div className="pending-file-asset" role="cell">
                          <label className="admin-check">
                            <input type="checkbox" checked={checked.has(item.id)} onChange={() => toggleChecked(item.id)} aria-label={`选择 ${item.name}`} />
                            <span><Check size={13} weight="bold" /></span>
                          </label>
                          <img src={item.thumbnailUrl} alt="" loading="lazy" decoding="async" onError={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = ADMIN_PREVIEW_FALLBACK; }} />
                          <span className="pending-file-copy">
                            <strong>{item.name}</strong>
                            <small>{item.relPath}</small>
                            <em>{item.discoveredAt}</em>
                          </span>
                        </div>
                        <div className="pending-file-sku" role="cell">
                          <strong className={item.sku ? "is-recognized" : ""}>{item.sku ? `SKU ${item.sku}` : "SKU 未识别"}</strong>
                          {!isDisabledView && <button type="button" onClick={() => item.status === "pending" ? runSuggestion([item.id]) : setActiveItemId(item.id)}>{item.status === "pending" ? "建议识别" : "查看建议"}</button>}
                        </div>
                        <div className={`pending-file-target ${item.driveFolder ? "" : "is-empty"}`} role="cell">
                          <strong>{item.driveFolder ? `/${item.driveFolder}/` : isDisabledView ? "原素材信息已保留" : "等待生成建议"}</strong>
                          {!isDisabledView && <button type="button" onClick={() => setActiveItemId(item.id)}>{item.driveFolder ? "修改建议" : "设置目录"}</button>}
                        </div>
                        <div className="pending-file-action" role="cell">
                          {isDisabledView
                            ? <button type="button" onClick={() => restoreItems([item.id])}><ArrowCounterClockwise size={17} weight="bold" /> 恢复</button>
                            : <button type="button" onClick={() => setActiveItemId(item.id)}><Eye size={17} weight="bold" /> 审核</button>}
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="pending-detail-empty">
                {isDisabledView ? <Archive size={36} weight="duotone" /> : <CheckCircle size={36} weight="duotone" />}
                <strong>{isDisabledView ? "暂时弃用中没有素材" : "没有匹配的待办"}</strong>
                <span>{isDisabledView ? "被暂时弃用的批次会保留在这里。" : "调整搜索关键词后再试。"}</span>
              </div>
            )}
          </section>
        </div>

        <footer className="pending-action-bar">
          <div className="pending-action-summary">
            <strong>已选择 {checked.size} 个素材</strong>
            {pageCount > 1 && (
              <nav className="pending-pagination" aria-label={isDisabledView ? "暂时弃用素材分页" : "待确认素材分页"}>
                <button type="button" onClick={() => onPageChange(page - 1)} disabled={loading || page <= 1} aria-label="上一页"><CaretLeft size={16} weight="bold" /></button>
                <span>{page} / {pageCount}</span>
                <button type="button" onClick={() => onPageChange(page + 1)} disabled={loading || page >= pageCount} aria-label="下一页"><CaretRight size={16} weight="bold" /></button>
              </nav>
            )}
            <small>本页 {visibleBatches.length} 个批次、{imports.length} 条素材 · 共 {batchTotal} 个批次、{total} 条素材 · 每页 {pageSize} 个批次</small>
          </div>
          <div className="pending-action-buttons">
            {isDisabledView ? (
              <button type="button" onClick={() => restoreItems([...checked])} disabled={!checked.size}><ArrowCounterClockwise size={17} weight="bold" /> 恢复所选</button>
            ) : (
              <>
                <button type="button" onClick={() => rejectItems([...checked])} disabled={!checked.size}><Archive size={17} weight="bold" /> 暂时弃用</button>
                <button type="button" className="is-primary" onClick={() => selectedBatch && setActiveBatchId(selectedBatch.id)} disabled={!selectedBatch}><CheckCircle size={17} weight="bold" /> 开始整批审批</button>
              </>
            )}
          </div>
        </footer>
      </section>

      {!isDisabledView && activeItem && <ReviewModal item={activeItem} categoryOptions={categoryOptions} themeOptions={themeOptions} folders={folderPaths} onFoldersChange={setFolderPaths} onNotify={onNotify} onClose={() => setActiveItemId(null)} onSuggest={runSuggestion} onSave={saveItem} onApprove={approveItem} onReject={rejectItem} />}
      {!isDisabledView && activeBatchId && activeBatchItems.length > 0 && <BatchFolderModal batchName={activeBatchName} items={activeBatchItems} categoryOptions={categoryOptions} themeOptions={themeOptions} folders={folderPaths} onFoldersChange={setFolderPaths} onNotify={onNotify} onClose={() => setActiveBatchId(null)} onSaveItems={saveItems} onSuggest={runSuggestion} onApply={(folder, setCode, categoryId, themes, updateThemes, approve) => applyBatchSettings(activeBatchId, folder, setCode, categoryId, themes, updateThemes, approve)} />}
    </section>
  );
}
