import { useEffect, useRef, useState } from "react";
import {
  ArrowsOutSimple,
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  FolderOpen,
  MagicWand,
  PencilSimple,
  Stack,
  WarningCircle,
  X,
  XCircle,
} from "@phosphor-icons/react";
import {
  batchIdentityValidationError,
  buildBatchDriveName,
  syncDriveFolderWithEnglishName,
  syncDriveNameWithEnglishName,
  type BatchIdentityValues,
} from "./batchIdentity";
import { DriveFolderPicker } from "./DriveFolderPicker";
import type { CategoryOption, PendingImport, ThemeOption } from "./types";

interface SharedFolderProps {
  folders: string[];
  onFoldersChange: (folders: string[]) => void;
  onNotify: (message: string) => void;
}

interface ReviewModalProps extends SharedFolderProps {
  item: PendingImport;
  categoryOptions: CategoryOption[];
  themeOptions: ThemeOption[];
  onClose: () => void;
  onSuggest: (ids: number[]) => Promise<void>;
  onSave: (draft: PendingImport) => Promise<void>;
  onApprove: (draft: PendingImport) => Promise<void>;
  onReject: (draft: PendingImport) => Promise<void>;
}

const statusLabel = { pending: "待建议", suggested: "待确认", error: "需处理", rejected: "暂时弃用" } as const;

function ImportReviewMedia({ item }: { item: PendingImport }) {
  if (item.assetType === "video" && item.mediaUrl) {
    return (
      <video
        src={item.mediaUrl}
        poster={item.thumbnailUrl}
        controls
        playsInline
        preload="metadata"
      />
    );
  }
  return <img src={item.thumbnailUrl} alt={item.driveName || item.name} />;
}

function useModalLifecycle(onClose: () => void) {
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);
}

interface ThemeSelectorProps {
  options: ThemeOption[];
  value: string[];
  onChange: (value: string[]) => void;
  batch?: boolean;
}

function ThemeSelector({ options, value, onChange, batch = false }: ThemeSelectorProps) {
  if (!options.length) return null;

  return (
    <fieldset className="intake-theme-field is-wide">
      <legend>主题 Theme（可多选）</legend>
      {batch && <p>勾选或取消后统一覆盖本批素材；不操作则保留每条素材原有主题。</p>}
      <div>
        {options.map((option) => {
          const checked = value.includes(option.id);
          return (
            <label key={option.id} className={checked ? "is-selected" : ""}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onChange(checked ? value.filter((theme) => theme !== option.id) : [...value, option.id])}
              />
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function ReviewModal({ item, categoryOptions, themeOptions, folders, onFoldersChange, onNotify, onClose, onSuggest, onSave, onApprove, onReject }: ReviewModalProps) {
  const [draft, setDraft] = useState(item);
  const [busy, setBusy] = useState<"suggest" | "save" | "approve" | "reject" | null>(null);
  useModalLifecycle(onClose);
  useEffect(() => setDraft(item), [item]);

  const perform = async (action: NonNullable<typeof busy>, callback: () => Promise<void>, closeAfter = false) => {
    setBusy(action);
    try {
      await callback();
      if (closeAfter) onClose();
    } finally {
      setBusy(null);
    }
  };

  const categoryRequired = draft.driveFolder.startsWith("04 Product Images");
  const ready = Boolean(draft.sku && draft.englishName && draft.driveFolder && draft.driveName && (!categoryRequired || draft.categoryId));
  const categoryGroups = [...new Set(categoryOptions.map((item) => item.group))];

  return (
    <div className="review-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="review-modal" role="dialog" aria-modal="true" aria-labelledby="review-modal-title">
        <header className="review-modal-heading">
          <div><span>单条素材审核 · {draft.batchName}</span><h2 id="review-modal-title">{draft.name}</h2><small>{draft.relPath}</small></div>
          <button type="button" onClick={onClose} aria-label="关闭审核弹窗"><X size={20} weight="bold" /></button>
        </header>

        <div className="review-modal-body">
          <div className="review-modal-preview">
            <ImportReviewMedia item={draft} />
            <span className={`admin-status ${draft.status}`}>{statusLabel[draft.status]}</span>
            <div><FolderOpen size={18} weight="duotone" /><span><strong>来源路径</strong><small>{draft.relPath}</small></span></div>
          </div>

          <div className="review-modal-form">
            <div className={`ai-note ${draft.status === "error" ? "has-error" : ""}`}>
              <span>{draft.status === "error" ? <WarningCircle size={17} weight="fill" /> : <MagicWand size={17} weight="fill" />} AI 建议 {draft.confidence ? `· ${Math.round(draft.confidence * 100)}%` : ""}</span>
              <p>{draft.error || draft.reason}</p>
            </div>
            <div className={`classification-note ${draft.categoryNeedsReview ? "needs-review" : "is-verified"}`}>
              <span>{draft.categoryNeedsReview ? <WarningCircle size={17} weight="fill" /> : <CheckCircle size={17} weight="fill" />} 固定分类建议 {draft.categoryConfidence ? `· ${Math.round(draft.categoryConfidence * 100)}%` : ""}</span>
              <p>{draft.categoryReason}</p>
            </div>
            <div className="admin-form-grid">
              <label>SKU<input value={draft.sku} onChange={(event) => setDraft({ ...draft, sku: event.target.value })} placeholder="例如 6012159" /></label>
              <label>英文品名<input value={draft.englishName} onChange={(event) => setDraft((current) => {
                const englishName = event.target.value;
                return {
                  ...current,
                  englishName,
                  driveName: syncDriveNameWithEnglishName(current.driveName, current.sku, current.englishName, englishName),
                  driveFolder: syncDriveFolderWithEnglishName(current.driveFolder, current.sku, current.englishName, englishName),
                };
              })} /></label>
              <label className="is-wide">目标目录
                <DriveFolderPicker value={draft.driveFolder} folders={folders} onFoldersChange={onFoldersChange} onChange={(driveFolder) => setDraft({ ...draft, driveFolder })} onNotify={onNotify} />
              </label>
              <label>目标文件名<input value={draft.driveName} onChange={(event) => setDraft({ ...draft, driveName: event.target.value })} /></label>
              <label>素材类型<select value={draft.assetType} onChange={(event) => setDraft({ ...draft, assetType: event.target.value as PendingImport["assetType"] })}><option value="image">图片</option><option value="video">视频</option><option value="kol_ugc">KOL / UGC</option><option value="ads">广告素材</option><option value="other">其他</option></select></label>
              <label>套装编号<input value={draft.setCode} onChange={(event) => setDraft({ ...draft, setCode: event.target.value })} placeholder="例如 Set00264" /></label>
              <label className="is-wide">固定产品分类
                <select value={draft.categoryId} onChange={(event) => setDraft({ ...draft, categoryId: event.target.value, categoryNeedsReview: false })}>
                  <option value="">{categoryRequired ? "请选择后才能入库" : "非产品素材无需分类"}</option>
                  {categoryGroups.map((group) => <optgroup label={group} key={group}>{categoryOptions.filter((item) => item.group === group).map((option) => <option value={option.id} key={option.id}>{option.labelZh} / {option.labelEn}</option>)}</optgroup>)}
                </select>
              </label>
              <ThemeSelector options={themeOptions} value={draft.themes} onChange={(themes) => setDraft({ ...draft, themes })} />
            </div>
          </div>
        </div>

        <footer className="review-modal-actions">
          <button className="button button-secondary is-danger" type="button" onClick={() => perform("reject", () => onReject(draft), true)} disabled={Boolean(busy)}><XCircle size={17} weight="bold" /> {busy === "reject" ? "正在弃用" : "暂时弃用"}</button>
          <span />
          {draft.status === "pending" ? <button className="button button-secondary" type="button" onClick={() => perform("suggest", () => onSuggest([draft.id]))} disabled={Boolean(busy)}><MagicWand size={17} weight="bold" /> {busy === "suggest" ? "正在生成" : "生成建议"}</button> : <button className="button button-secondary" type="button" onClick={() => perform("save", () => onSave(draft), true)} disabled={Boolean(busy)}>{busy === "save" ? "正在保存" : "保存修改"}</button>}
          <button className="button button-primary" type="button" onClick={() => perform("approve", () => onApprove(draft), true)} disabled={Boolean(busy) || !ready}><CheckCircle size={17} weight="bold" /> {busy === "approve" ? "正在入库" : "确认入库"}</button>
        </footer>
      </section>
    </div>
  );
}

interface BatchFolderModalProps extends SharedFolderProps {
  batchName: string;
  items: PendingImport[];
  categoryOptions: CategoryOption[];
  themeOptions: ThemeOption[];
  onClose: () => void;
  onSaveItems: (drafts: PendingImport[]) => Promise<void>;
  onSuggest: (ids: number[]) => Promise<void>;
  onApply: (folder: string, setCode: string, categoryId: string, themes: string[], updateThemes: boolean, approve: boolean) => Promise<void>;
}

type BatchApprovalStep = 1 | 2 | 3;

function itemIdentityReady(item: PendingImport) {
  return Boolean(item.sku && item.englishName && item.driveName);
}

export function BatchFolderModal({ batchName, items, categoryOptions, themeOptions, folders, onFoldersChange, onNotify, onClose, onSaveItems, onSuggest, onApply }: BatchFolderModalProps) {
  const existingFolders = [...new Set(items.map((item) => item.driveFolder).filter(Boolean))];
  const existingSetCodes = [...new Set(items.map((item) => item.setCode).filter(Boolean))];
  const existingCategoryIds = [...new Set(items.map((item) => item.categoryId).filter(Boolean))];
  const existingThemes = [...new Set(items.map((item) => [...item.themes].sort().join("|")))];
  const suggestedBatchFolder = existingFolders.length === 1 ? existingFolders[0] : "";
  const suggestedBatchSetCode = existingSetCodes.length === 1 ? existingSetCodes[0] : "";
  const suggestedBatchCategoryId = existingCategoryIds.length === 1 ? existingCategoryIds[0] : "";
  const [step, setStep] = useState<BatchApprovalStep>(items.every(itemIdentityReady) ? 2 : items.some((item) => item.status === "pending") ? 1 : 2);
  const [folder, setFolder] = useState(suggestedBatchFolder);
  const [folderTouched, setFolderTouched] = useState(false);
  const previousSuggestedBatchFolder = useRef(suggestedBatchFolder);
  const [setCode, setSetCode] = useState(suggestedBatchSetCode);
  const [categoryId, setCategoryId] = useState(suggestedBatchCategoryId);
  const [themes, setThemes] = useState<string[]>(existingThemes.length === 1 ? existingThemes[0].split("|").filter(Boolean) : []);
  const [themesTouched, setThemesTouched] = useState(false);
  const [busy, setBusy] = useState<"suggest" | "apply" | "approve" | null>(null);
  const [identityDraft, setIdentityDraft] = useState<BatchIdentityValues | null>(null);
  const [identityBusy, setIdentityBusy] = useState(false);
  const [identityError, setIdentityError] = useState("");
  const [reviewView, setReviewView] = useState<"gallery" | "compact">("gallery");
  const [focusedItemId, setFocusedItemId] = useState<number | null>(items[0]?.id ?? null);
  const [previewItem, setPreviewItem] = useState<PendingImport | null>(null);
  useModalLifecycle(onClose);

  useEffect(() => {
    if (!items.some((item) => item.id === focusedItemId)) {
      setFocusedItemId(items[0]?.id ?? null);
    }
  }, [focusedItemId, items]);

  useEffect(() => {
    const previous = previousSuggestedBatchFolder.current;
    if (suggestedBatchFolder && !folderTouched) {
      setFolder((current) => (!current || current === previous ? suggestedBatchFolder : current));
    }
    previousSuggestedBatchFolder.current = suggestedBatchFolder;
  }, [folderTouched, suggestedBatchFolder]);

  useEffect(() => {
    if (suggestedBatchSetCode) setSetCode((current) => current || suggestedBatchSetCode);
  }, [suggestedBatchSetCode]);

  useEffect(() => {
    if (suggestedBatchCategoryId) setCategoryId((current) => current || suggestedBatchCategoryId);
  }, [suggestedBatchCategoryId]);

  const suggest = async () => {
    setBusy("suggest");
    try {
      await onSuggest(items.map((item) => item.id));
      setStep(2);
    } finally {
      setBusy(null);
    }
  };

  const apply = async (approve: boolean) => {
    if (!approve && !folder && !setCode && !categoryId && !themesTouched) return;
    setBusy(approve ? "approve" : "apply");
    try {
      await onApply(folder, setCode, categoryId, themes, themesTouched, approve);
      onClose();
    } finally {
      setBusy(null);
    }
  };

  const readyAfterFolder = items.every((item) => {
    const targetFolder = folder || item.driveFolder;
    return item.sku && item.englishName && item.driveName && targetFolder && (!targetFolder.startsWith("04 Product Images") || categoryId || item.categoryId);
  });
  const hasBatchChange = Boolean(folder || setCode || categoryId || themesTouched);
  const identityReadyCount = items.filter(itemIdentityReady).length;
  const identityIssueItems = items.filter((item) => !itemIdentityReady(item));
  const errorCount = items.filter((item) => item.status === "error").length;
  const suggestionCount = items.filter((item) => item.status !== "pending" || item.sku || item.englishName || item.driveFolder).length;
  const categoryGroups = [...new Set(categoryOptions.map((item) => item.group))];
  const steps: { id: BatchApprovalStep; label: string; hint: string }[] = [
    { id: 1, label: "AI 生成建议", hint: "生成 SKU 和英文品名" },
    { id: 2, label: "核对整批", hint: "看清结果，有错统一修改" },
    { id: 3, label: "设置并入库", hint: "确认目录后整批入库" },
  ];
  const goToStep = (nextStep: BatchApprovalStep) => {
    if (nextStep === 3 && (step === 1 || identityIssueItems.length)) return;
    if (nextStep === 2 && !suggestionCount && step === 1) return;
    setStep(nextStep);
  };

  const openIdentityEditor = () => {
    const firstWithSku = items.find((item) => item.sku)?.sku || "";
    const firstWithEnglishName = items.find((item) => item.englishName)?.englishName || "";
    const firstWithDriveName = items.find((item) => item.driveName)?.driveName || items[0]?.name || "";
    setIdentityDraft({
      sku: firstWithSku,
      englishName: firstWithEnglishName,
      driveName: firstWithDriveName,
    });
    setIdentityError("");
  };

  const closeIdentityEditor = () => {
    if (identityBusy) return;
    setIdentityDraft(null);
    setIdentityError("");
  };

  const updateIdentityDraft = (field: keyof BatchIdentityValues, value: string) => {
    setIdentityDraft((current) => current ? { ...current, [field]: value } : current);
    setIdentityError("");
  };

  const updateIdentityEnglishName = (englishName: string) => {
    setIdentityDraft((current) => current ? {
      ...current,
      englishName,
      driveName: syncDriveNameWithEnglishName(current.driveName, current.sku, current.englishName, englishName),
    } : current);
    setIdentityError("");
  };

  const saveIdentity = async () => {
    if (!identityDraft) return;
    const validationError = batchIdentityValidationError(identityDraft);
    if (validationError) {
      setIdentityError(validationError);
      return;
    }
    setIdentityBusy(true);
    setIdentityError("");
    try {
      const sku = identityDraft.sku.trim();
      const englishName = identityDraft.englishName.trim();
      const nextItems = items.map((item, index) => ({
        ...item,
        sku,
        englishName,
        driveName: buildBatchDriveName(identityDraft.driveName, item, index, items.length),
        driveFolder: syncDriveFolderWithEnglishName(item.driveFolder, sku, item.englishName, englishName),
      }));
      await onSaveItems(nextItems);
      setIdentityDraft(null);
    } catch (error) {
      setIdentityError(error instanceof Error ? error.message : "保存失败，请检查输入后重试。");
    } finally {
      setIdentityBusy(false);
    }
  };

  return (
    <div className="review-modal-backdrop batch-approval-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="batch-folder-modal batch-settings-modal batch-approval-modal" role="dialog" aria-modal="true" aria-labelledby="batch-folder-title">
        <header className="review-modal-heading batch-settings-heading">
          <div className="batch-settings-title">
            <span className="batch-settings-icon"><Stack size={21} weight="duotone" /></span>
            <span className="batch-settings-heading-copy">
              <em>批量审批 · 第 {step} 步，共 3 步</em>
              <h2 id="batch-folder-title">{batchName}</h2>
              <small>{items.length} 个素材 · 按顺序完成即可，不会跳过核对直接入库</small>
            </span>
          </div>
          <div className="batch-settings-heading-actions">
            <button className="batch-settings-close" type="button" onClick={onClose} aria-label="关闭整批审批弹窗"><X size={20} weight="bold" /></button>
          </div>
        </header>
        <nav className="batch-approval-steps" aria-label="批量审批步骤">
          {steps.map((item) => {
            const complete = step > item.id || (item.id === 1 && identityReadyCount === items.length);
            const disabled = (item.id === 2 && !suggestionCount && step === 1) || (item.id === 3 && (step === 1 || identityIssueItems.length > 0));
            return (
              <button
                type="button"
                key={item.id}
                className={`${step === item.id ? "is-active" : ""} ${complete ? "is-complete" : ""}`}
                onClick={() => goToStep(item.id)}
                disabled={disabled}
                aria-current={step === item.id ? "step" : undefined}
              >
                <i>{complete ? <CheckCircle size={18} weight="fill" /> : item.id}</i>
                <span><strong>{item.label}</strong><small>{item.hint}</small></span>
              </button>
            );
          })}
        </nav>

        <div className={`batch-folder-body batch-settings-body batch-approval-body is-step-${step}`}>
          {step === 1 && (
            <section className="batch-approval-intro">
              <div className="batch-approval-intro-icon"><MagicWand size={34} weight="duotone" /></div>
              <div className="batch-approval-intro-copy">
                <span>第一步</span>
                <h3>先让 AI 把资料整理出来</h3>
                <p>系统会为每个素材生成 <strong>SKU、英文品名、产品分类和目标目录</strong>。这里只生成建议，不会自动入库。</p>
              </div>
              <div className="batch-approval-counts" aria-label="AI 建议生成状态">
                <span><strong>{items.length}</strong><small>本批素材</small></span>
                <span className={suggestionCount ? "is-good" : ""}><strong>{suggestionCount}</strong><small>已有建议</small></span>
                <span className={errorCount ? "is-alert" : ""}><strong>{errorCount}</strong><small>生成异常</small></span>
              </div>
              <div className="batch-approval-file-sample">
                <strong>将处理这些素材</strong>
                <div>{items.slice(0, 4).map((item) => <span key={item.id}>{item.name}</span>)}</div>
                {items.length > 4 && <small>以及另外 {items.length - 4} 个素材</small>}
              </div>
              <div className="batch-approval-safety-note">
                <CheckCircle size={20} weight="fill" />
                <span><strong>放心操作</strong><small>生成后会进入“逐条核对”，看清 SKU 和英文品名后才允许入库。</small></span>
              </div>
            </section>
          )}

          {step === 2 && (
            <section className="batch-review-stage">
              <header className="batch-review-heading">
                <div><span>第二步</span><h3>检查本批 AI 生成结果</h3><p>本批属于同一产品，只需修改一次；保存后会同步到本批全部素材。</p></div>
                <div className={identityIssueItems.length ? "has-issues" : "is-ready"}>
                  {identityIssueItems.length ? <WarningCircle size={23} weight="fill" /> : <CheckCircle size={23} weight="fill" />}
                  <span><strong>{identityReadyCount} / {items.length} 条信息完整</strong><small>{identityIssueItems.length ? `还有 ${identityIssueItems.length} 条需要处理` : "可以进入下一步"}</small></span>
                  <button className="batch-review-edit-all" type="button" onClick={openIdentityEditor}><PencilSimple size={15} weight="bold" /> 修改整批信息</button>
                </div>
              </header>
              <div className="batch-review-view-controls">
                <span>查看方式：</span>
                <div role="group" aria-label="审核结果查看方式">
                  <button type="button" className={reviewView === "gallery" ? "is-active" : ""} onClick={() => setReviewView("gallery")} aria-pressed={reviewView === "gallery"}>大图</button>
                  <button type="button" className={reviewView === "compact" ? "is-active" : ""} onClick={() => setReviewView("compact")} aria-pressed={reviewView === "compact"}>紧凑</button>
                </div>
              </div>
              {reviewView === "gallery" ? (
                <div className="batch-review-gallery" aria-label="AI 批量建议结果">
                  {items.map((item) => {
                    const ready = itemIdentityReady(item);
                    const focused = focusedItemId === item.id;
                    return (
                      <article
                        className={`batch-review-card ${ready ? "is-ready" : "has-issue"} ${focused ? "is-focused" : ""}`}
                        key={item.id}
                        tabIndex={0}
                        onFocus={() => setFocusedItemId(item.id)}
                        onMouseEnter={() => setFocusedItemId(item.id)}
                      >
                        <div className="batch-review-card-media">
                          <img src={item.thumbnailUrl} alt={item.driveName || item.name} loading="lazy" decoding="async" />
                          <button type="button" onClick={() => setPreviewItem(item)} aria-label={`放大查看 ${item.driveName || item.name}`}><ArrowsOutSimple size={18} weight="bold" /></button>
                        </div>
                        <div className="batch-review-card-copy">
                          <h4 title={item.driveName || item.name}>{item.driveName || item.name}</h4>
                          <dl>
                            <div><dt>SKU</dt><dd className={item.sku ? "" : "is-missing"}>{item.sku || "未生成 SKU"}</dd></div>
                            <div><dt>英文品名</dt><dd className={item.englishName ? "" : "is-missing"}>{item.englishName || "未生成英文品名"}</dd></div>
                          </dl>
                          <span className={`batch-review-card-result ${ready ? "is-ready" : "has-issue"}`}>
                            {ready ? <CheckCircle size={17} weight="fill" /> : <WarningCircle size={17} weight="fill" />}
                            {ready ? "信息完整" : "需要补充"}
                          </span>
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="batch-review-table" role="table" aria-label="AI 批量建议结果紧凑视图">
                  <div className="batch-review-table-head" role="row">
                    <span role="columnheader">文件名</span>
                    <span role="columnheader">SKU</span>
                    <span role="columnheader">英文品名</span>
                    <span role="columnheader">检查结果</span>
                  </div>
                  <div className="batch-review-table-body">
                    {items.map((item) => {
                      const ready = itemIdentityReady(item);
                      return (
                        <article className={`batch-review-row ${ready ? "is-ready" : "has-issue"}`} role="row" key={item.id}>
                          <div className="batch-review-file" role="cell">
                            <img src={item.thumbnailUrl} alt="" loading="lazy" decoding="async" />
                            <span><small className="batch-review-cell-label">文件名</small><strong title={item.driveName || item.name}>{item.driveName || item.name}</strong></span>
                          </div>
                          <div className="batch-review-value" role="cell"><small className="batch-review-cell-label">SKU</small>{item.sku ? <strong>{item.sku}</strong> : <em>未生成 SKU</em>}</div>
                          <div className="batch-review-value is-name" role="cell"><small className="batch-review-cell-label">英文品名</small>{item.englishName ? <strong>{item.englishName}</strong> : <em>未生成英文品名</em>}</div>
                          <div className="batch-review-result" role="cell"><span className={ready ? "is-ready" : "has-issue"}>{ready ? <CheckCircle size={16} weight="fill" /> : <WarningCircle size={16} weight="fill" />}{ready ? "信息完整" : "需要补充"}</span></div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}
              {identityIssueItems.length > 0 && (
                <div className="batch-review-blocker">
                  <WarningCircle size={19} weight="fill" />
                  <span><strong>暂时不能进入下一步</strong><small>请先补齐 {identityIssueItems.length} 条素材的 SKU、英文品名或目标文件名。</small></span>
                </div>
              )}
            </section>
          )}

          {step === 3 && (
            <section className="batch-final-stage">
              <header className="batch-final-heading">
                <span><CheckCircle size={22} weight="fill" /></span>
                <div><small>第三步</small><h3>统一设置目录，然后确认入库</h3><p>{items.length} 条素材的 SKU 和英文品名已经核对完成。</p></div>
              </header>
              <section className="batch-settings-section batch-directory-section">
                <header><span><FolderOpen size={18} weight="duotone" /><strong>目标目录</strong></span><small>选择后统一覆盖本批素材的目录</small></header>
                <DriveFolderPicker value={folder} folders={folders} onFoldersChange={onFoldersChange} onChange={(nextFolder) => { setFolder(nextFolder); setFolderTouched(true); }} onNotify={onNotify} />
                {!folder && existingFolders.length > 1 && (
                  <div className="batch-generated-directories">
                    <strong>AI 已生成 {existingFolders.length} 个不同目录</strong>
                    <div>{existingFolders.map((path) => <span key={path} title={path}>{path}</span>)}</div>
                    <small>不统一修改时，将保留每个文件自己的 AI 目录。</small>
                  </div>
                )}
                {!folder && existingFolders.length === 0 && <p className="batch-directory-help has-issue">AI 尚未生成可用目录，请在这里选择目标目录后再入库。</p>}
              </section>
              <div className="batch-metadata-grid">
                <label className="batch-settings-section"><span>产品分类</span><small>留空时保留每条素材的原分类</small><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">保留各自分类</option>{categoryGroups.map((group) => <optgroup label={group} key={group}>{categoryOptions.filter((item) => item.group === group).map((option) => <option value={option.id} key={option.id}>{option.labelZh} / {option.labelEn}</option>)}</optgroup>)}</select></label>
                <label className="batch-settings-section"><span>套装编号</span><small>同系列素材可设置统一套装编号</small><input value={setCode} onChange={(event) => setSetCode(event.target.value)} placeholder="例如 Set00264（留空则保留）" /></label>
              </div>
              <section className="batch-settings-section batch-theme-section">
                <ThemeSelector
                  options={themeOptions}
                  value={themes}
                  onChange={(nextThemes) => { setThemes(nextThemes); setThemesTouched(true); }}
                  batch
                />
              </section>
              <div className={`batch-scope-summary ${readyAfterFolder ? "is-ready" : "has-issue"}`}>
                {readyAfterFolder ? <CheckCircle size={18} weight="fill" /> : <WarningCircle size={18} weight="fill" />}
                <span>
                  <strong>{readyAfterFolder ? `已准备好入库 ${items.length} 个素材` : "还需要确认目标目录或产品分类"}</strong>
                  <small>{readyAfterFolder ? "点击“确认整批入库”后才会正式写入素材库。" : "产品图片必须同时具备目录和产品分类。"}</small>
                </span>
              </div>
            </section>
          )}
        </div>

        <footer className="review-modal-actions compact batch-settings-actions batch-approval-actions">
          <button className="button button-secondary" type="button" onClick={onClose}>取消</button>
          <span />
          {step === 1 && (
            <>
              {suggestionCount > 0 && <button className="button button-secondary" type="button" onClick={() => setStep(2)} disabled={Boolean(busy)}>查看已有结果</button>}
              <button className="button button-primary batch-suggest-button" type="button" onClick={suggest} disabled={Boolean(busy)}><MagicWand size={17} weight="bold" /> {busy === "suggest" ? "正在生成，请稍候" : suggestionCount ? "重新生成并查看结果" : "生成 AI 建议并查看"}</button>
            </>
          )}
          {step === 2 && (
            <>
              <button className="button batch-suggest-button" type="button" onClick={suggest} disabled={Boolean(busy)}><MagicWand size={16} weight="bold" /> {busy === "suggest" ? "正在重新生成" : "重新生成建议"}</button>
              <button className="button button-secondary" type="button" onClick={() => setStep(1)} disabled={Boolean(busy)}><ArrowLeft size={16} weight="bold" /> 上一步</button>
              <button className="button button-primary" type="button" onClick={() => setStep(3)} disabled={Boolean(busy) || identityIssueItems.length > 0}>下一步：设置入库信息 <ArrowRight size={16} weight="bold" /></button>
            </>
          )}
          {step === 3 && (
            <>
              <button className="button button-secondary" type="button" onClick={() => setStep(2)} disabled={Boolean(busy)}><ArrowLeft size={16} weight="bold" /> 上一步：核对结果</button>
              <button className="button button-secondary" type="button" onClick={() => apply(false)} disabled={!hasBatchChange || Boolean(busy)}>{busy === "apply" ? "正在保存" : "仅保存设置"}</button>
              <button className="button button-primary" type="button" onClick={() => apply(true)} disabled={!readyAfterFolder || Boolean(busy)}><CheckCircle size={17} weight="bold" /> {busy === "approve" ? "正在整批入库" : `确认整批入库（${items.length}）`}</button>
            </>
          )}
        </footer>

        {previewItem && (
          <div className="batch-image-preview-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreviewItem(null); }}>
            <section className="batch-image-preview" role="dialog" aria-modal="true" aria-label={`查看 ${previewItem.driveName || previewItem.name}`}>
              <button type="button" onClick={() => setPreviewItem(null)} aria-label="关闭大图预览"><X size={22} weight="bold" /></button>
              <ImportReviewMedia item={previewItem} />
              <strong>{previewItem.driveName || previewItem.name}</strong>
            </section>
          </div>
        )}

        {identityDraft && (
          <div className="batch-identity-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeIdentityEditor(); }}>
            <section className="batch-identity-editor" role="dialog" aria-modal="true" aria-labelledby="batch-identity-title">
              <header>
                <div>
                  <span>整批修改 · 共 {items.length} 个素材</span>
                  <h3 id="batch-identity-title">修改整批 SKU、英文品名和文件名</h3>
                  <p>保存后同步更新整批，不会改动目录、分类或主题。</p>
                </div>
                <button type="button" onClick={closeIdentityEditor} disabled={identityBusy} aria-label="关闭信息修改弹窗"><X size={20} weight="bold" /></button>
              </header>
              <div className="batch-identity-fields">
                <div className="batch-identity-scope">
                  <CheckCircle size={20} weight="fill" />
                  <span><strong>将更新本批 {items.length} 个素材</strong><small>SKU 和英文品名统一；文件名保留各自编号与扩展名，避免重名。</small></span>
                </div>
                {identityError && (
                  <div className="batch-identity-error" role="alert">
                    <WarningCircle size={20} weight="fill" />
                    <span>
                      <strong>无法保存，请检查下面内容</strong>
                      <small>{identityError}</small>
                    </span>
                  </div>
                )}
                <label>
                  <span>SKU</span>
                  <input value={identityDraft.sku} onChange={(event) => updateIdentityDraft("sku", event.target.value)} />
                </label>
                <label>
                  <span>英文品名</span>
                  <textarea rows={2} value={identityDraft.englishName} onChange={(event) => updateIdentityEnglishName(event.target.value)} />
                </label>
                <label>
                  <span>文件名主体</span>
                  <textarea rows={2} value={identityDraft.driveName} onChange={(event) => updateIdentityDraft("driveName", event.target.value)} />
                  <small className="batch-identity-field-help">多素材时自动保留（1）、（2）等原有编号以及各自扩展名。</small>
                </label>
              </div>
              <footer>
                <button className="button button-secondary" type="button" onClick={closeIdentityEditor} disabled={identityBusy}>取消</button>
                <button className="button button-primary" type="button" onClick={saveIdentity} disabled={identityBusy || !identityDraft.sku.trim() || !identityDraft.englishName.trim() || !identityDraft.driveName.trim()}>
                  <CheckCircle size={17} weight="bold" /> {identityBusy ? "正在保存整批" : `保存并应用到整批（${items.length}）`}
                </button>
              </footer>
            </section>
          </div>
        )}
      </section>
    </div>
  );
}
