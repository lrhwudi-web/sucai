import { apiEnabled } from "../services/auth";
import { mockProducts } from "../data/mockData";
import { demoImportJobs, editLogs, initialPendingImports, initialRules, initialUsers, uploadHistory } from "./mockAdminData";
import type {
  AdminMessage,
  AdminOverview,
  AdminProductPage,
  CategoryOption,
  CategoryTagOption,
  CustomerAccessOverview,
  ImportJob,
  PendingImport,
  ImportView,
  ThemeOption,
} from "./types";

interface RawOverview {
  users: Array<{ id: number; email: string; name: string; role: string; permission_mode?: string; disabled?: number | boolean; expires_at?: string; created_at: string }>;
  rules: Array<{ id: number; role: string; scope: string; value: string; created_at: string }>;
  user_grants: Array<{ id: number; user_id: number; name: string; email: string; scope: string; value: string; created_at: string }>;
  can_manage_access: boolean;
  sync_status: null | { state: string; message: string; root_id: string; file_count: number; started_at: string; finished_at: string };
  imports: Array<Record<string, unknown>>;
  import_total: number;
  import_batch_total: number;
  import_batch_count: number;
  import_page: number;
  import_page_size: number;
  import_pages: number;
  import_view: ImportView;
  active_import_total: number;
  disabled_import_total: number;
  import_status_counts: Record<string, number>;
  edit_logs: Array<Record<string, unknown>>;
  upload_history: Array<Record<string, unknown>>;
  permission_values: Record<string, string[]>;
  role_labels: Record<string, string>;
  scope_labels: Record<string, string>;
  category_options: Array<Record<string, unknown>>;
  category_tag_options: Array<Record<string, unknown>>;
  theme_options: Array<Record<string, unknown>>;
  message_count: number;
}

interface RawCustomerAccessOverview {
  users: Array<{ id: number; email: string; name: string; role: string; permission_mode?: string; disabled?: number | boolean; expires_at?: string; created_at: string; created_by_user_id?: number | null; created_by_name?: string }>;
  salespeople?: Array<{ id: number; email: string; name: string; role: string; disabled?: number | boolean }>;
  rules: Array<{ id: number; role: string; scope: string; value: string; created_at: string }>;
  user_grants: Array<{ id: number; user_id: number; name: string; email: string; scope: string; value: string; created_at: string }>;
  permission_values: Record<string, string[]>;
  role_labels: Record<string, string>;
  scope_labels: Record<string, string>;
}

const assetTypes = new Set(["image", "video", "kol_ugc", "ads", "other"]);
const demoCategoryOptions: CategoryOption[] = [
  { id: "HC_PLUSH", group: "Golf Headcover", labelZh: "毛绒杆套", labelEn: "Plush Covers" },
  { id: "HC_DRIVER", group: "Golf Headcover", labelZh: "一号木杆套", labelEn: "Driver Covers" },
  { id: "HC_FAIRWAY", group: "Golf Headcover", labelZh: "球道木杆套", labelEn: "Fairway Covers" },
  { id: "HC_HYBRID", group: "Golf Headcover", labelZh: "混合木杆套", labelEn: "Hybrid Covers" },
  { id: "HC_PUTTER_BLADE", group: "Golf Headcover", labelZh: "直条推杆套", labelEn: "Blade Putter Covers" },
  { id: "HC_PUTTER_MALLET_LARGE", group: "Golf Headcover", labelZh: "大半圆推杆套", labelEn: "Mallet Putter Covers" },
  { id: "HC_PUTTER_MALLET_SMALL", group: "Golf Headcover", labelZh: "小半圆推杆套", labelEn: "Mid-Mallet Putter Covers" },
  { id: "HC_PUTTER_SQUARE", group: "Golf Headcover", labelZh: "方形推杆套", labelEn: "Square Mallet Putter Covers" },
  { id: "HC_IRON", group: "Golf Headcover", labelZh: "铁杆套装", labelEn: "Iron Cover Sets" },
  { id: "HC_WEDGE", group: "Golf Headcover", labelZh: "挖起杆套装", labelEn: "Wedge Cover Sets" },
  { id: "HC_ALIGNMENT", group: "Golf Headcover", labelZh: "方向棒套", labelEn: "Alignment Stick Covers" },
  { id: "ACC_DIVOT_MARKER", group: "Golf Accessories", labelZh: "果岭叉与球位标", labelEn: "Divot Tools & Ball Markers" },
  { id: "ACC_SCORECARD", group: "Golf Accessories", labelZh: "记分卡夹", labelEn: "Scorecard Holders" },
  { id: "ACC_TOWEL", group: "Golf Accessories", labelZh: "高尔夫毛巾", labelEn: "Golf Towels" },
  { id: "ACC_BALL_TEE_POUCH", group: "Golf Accessories", labelZh: "球与球钉袋", labelEn: "Golf Ball & Tee Pouchs" },
  { id: "ACC_VALUABLES_POUCH", group: "Golf Accessories", labelZh: "贵重物品袋", labelEn: "Valuables Pouches" },
  { id: "ACC_GLOVE_CADDIE", group: "Golf Accessories", labelZh: "手套收纳架", labelEn: "Glove Caddie" },
  { id: "ACC_RANGEFINDER", group: "Golf Accessories", labelZh: "测距仪包", labelEn: "Rangefinder Case" },
  { id: "ACC_OTHER", group: "Golf Accessories", labelZh: "其他", labelEn: "Others" },
];
const demoCategoryTagOptions: CategoryTagOption[] = [
  { id: "PLUSH_ANIMAL", labelZh: "毛绒杆套（动物玩偶）", labelEn: "Plush / Animal" },
];
const demoThemeOptions: ThemeOption[] = [
  { id: "AMERICANA", label: "Americana" },
  { id: "LUCKY_CLOVER", label: "Lucky & Clover" },
  { id: "POP_CULTURE_ENTERTAINMENT", label: "Pop Culture & Entertainment" },
  { id: "FOOD_DRINKS", label: "Food & Drinks" },
  { id: "ANIMALS", label: "Animals" },
  { id: "WOMENS_GIRLS", label: "Women's & Girls" },
  { id: "SKULLS_GOTHIC", label: "Skulls & Gothic" },
  { id: "CLASSIC_RETRO", label: "Classic & Retro" },
  { id: "LIMITED_EDITION", label: "Limited Edition" },
];

const demoPermissionValues: Record<string, string[]> = {
  brand: ["01 Craftsman Golf", "02 My Tag", "03 Big Crazy", "04 Big Teeth", "05 Caesar", "No Brand"],
  category: ["01 Headcover Set", "02 Driver Cover", "04 Blade Putter Cover", "05 Mallet Putter Cover"],
  asset_type: ["image", "video", "kol_ugc", "ads", "other"],
  other: ["Product Catalogs", "Brand Assets", "Packaging Assets", "Show & Exhibitions", "Event Sponsorships", "Influencer Assets", "No Brand"],
  sku: ["6012318", "6012188", "6012034"],
};

const demoCustomerAccess: CustomerAccessOverview = {
  users: [
    { id: 101, email: "info@gravityaxis.co.th", name: "FLOG", role: "海外客户", permissionMode: "allowlist", disabled: false, createdAt: "08/28 14:30", createdByUserId: 901, createdByName: "刘芮华" },
    { id: 102, email: "johan@golfgeist.com", name: "Johan", role: "海外客户", permissionMode: "allowlist", disabled: false, createdAt: "08/28 14:16", createdByUserId: 901, createdByName: "刘芮华" },
    { id: 103, email: "bungigolf@gmail.com", name: "Esteban", role: "海外客户", permissionMode: "allowlist", disabled: false, createdAt: "08/07 10:24", createdByUserId: 902, createdByName: "黄彩丽" },
    { id: 104, email: "khalifa.hongli@gmail.com", name: "杨小姐", role: "国内客户", permissionMode: "role_default", disabled: false, createdAt: "08/03 08:58", createdByUserId: 902, createdByName: "黄彩丽" },
    { id: 105, email: "admin@example.com", name: "小凯", role: "海外客户", permissionMode: "allowlist", disabled: true, createdAt: "08/18 14:04", createdByUserId: 901, createdByName: "刘芮华" },
    { id: 106, email: "user1@example.com", name: "小凯", role: "海外客户", permissionMode: "allowlist", disabled: false, createdAt: "07/08 10:53", createdByUserId: 902, createdByName: "黄彩丽" },
  ],
  salespeople: [
    { id: 901, email: "liuruihua@example.com", name: "刘芮华", role: "super_admin", disabled: false },
    { id: 902, email: "sales@example.com", name: "黄彩丽", role: "admin", disabled: false },
  ],
  rules: [
    { id: 201, role: "海外客户", scope: "其他标签", value: "Influencer Assets", createdAt: "08/28 14:45" },
    { id: 202, role: "海外客户", scope: "其他标签", value: "No Brand", createdAt: "07/14 14:29" },
    { id: 203, role: "海外客户", scope: "其他标签", value: "Show & Exhibitions", createdAt: "08/28 14:46" },
  ],
  userGrants: [
    { id: 301, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "品牌", value: "01 Craftsman Golf", createdAt: "08/28 14:30" },
    { id: 302, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "品牌", value: "03 Big Crazy", createdAt: "08/28 14:30" },
    { id: 309, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "品牌", value: "02 My Tag", createdAt: "08/28 14:30" },
    { id: 310, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "品牌", value: "04 Big Teeth", createdAt: "08/28 14:30" },
    { id: 311, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "品牌", value: "05 Caesar", createdAt: "08/28 14:30" },
    { id: 312, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "其他标签", value: "Product Catalogs", createdAt: "08/28 14:30" },
    { id: 313, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "其他标签", value: "Brand Assets", createdAt: "08/28 14:30" },
    { id: 314, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "其他标签", value: "Packaging Assets", createdAt: "08/28 14:30" },
    { id: 315, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "其他标签", value: "Show & Exhibitions", createdAt: "08/28 14:30" },
    { id: 316, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "其他标签", value: "Event Sponsorships", createdAt: "08/28 14:30" },
    { id: 317, userId: 101, userName: "FLOG", userEmail: "info@gravityaxis.co.th", scope: "其他标签", value: "Influencer Assets", createdAt: "08/28 14:30" },
    { id: 303, userId: 102, userName: "Johan", userEmail: "johan@golfgeist.com", scope: "品牌", value: "05 Caesar", createdAt: "08/28 14:16" },
    { id: 304, userId: 102, userName: "Johan", userEmail: "johan@golfgeist.com", scope: "其他标签", value: "Show & Exhibitions", createdAt: "08/28 14:16" },
    { id: 305, userId: 103, userName: "Esteban", userEmail: "bungigolf@gmail.com", scope: "品牌", value: "No Brand", createdAt: "08/07 10:24" },
    { id: 306, userId: 105, userName: "小凯", userEmail: "admin@example.com", scope: "品牌", value: "02 My Tag", createdAt: "08/18 14:04" },
    { id: 307, userId: 106, userName: "小凯", userEmail: "user1@example.com", scope: "品牌", value: "04 Big Teeth", createdAt: "07/08 10:53" },
    { id: 308, userId: 106, userName: "小凯", userEmail: "user1@example.com", scope: "其他标签", value: "Event Sponsorships", createdAt: "07/08 10:53" },
  ],
  permissionValues: demoPermissionValues,
};

function text(value: unknown): string {
  return value == null ? "" : String(value);
}

function formatDate(value: unknown): string {
  const raw = text(value);
  if (!raw) return "—";
  const date = new Date(raw.endsWith("Z") ? raw : `${raw.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return raw;
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

function timestamp(value: unknown): number | null {
  const raw = text(value);
  if (!raw) return null;
  const parsed = new Date(raw.endsWith("Z") ? raw : `${raw.replace(" ", "T")}Z`).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function mapCategoryOption(row: Record<string, unknown>): CategoryOption {
  return {
    id: text(row.id),
    group: text(row.group),
    labelZh: text(row.label_zh),
    labelEn: text(row.label_en),
  };
}

function mapCategoryTagOption(row: Record<string, unknown>): CategoryTagOption {
  return {
    id: text(row.id),
    labelZh: text(row.label_zh),
    labelEn: text(row.label_en),
  };
}

function mapImport(row: Record<string, unknown>): PendingImport {
  const name = text(row.name);
  const relPath = text(row.rel_path).replaceAll("\\", "/");
  const sourceParts = relPath.split("/").filter(Boolean);
  const batchParts = sourceParts.at(-1) === name ? sourceParts.slice(0, -1) : sourceParts;
  const batchPath = batchParts.join("/") || `import-${text(row.id)}`;
  const rawStatus = text(row.status);
  const status = rawStatus === "suggested"
    ? "suggested"
    : rawStatus === "error"
      ? "error"
      : rawStatus === "rejected"
        ? "rejected"
        : "pending";
  const inferredAssetType = /\.(mp4|mov|m4v|webm|avi|mkv|wmv|mpeg|mpg)$/i.test(name) ? "video" : "image";
  const finalAssetType = text(row.final_asset_type) || text(row.suggested_asset_type) || inferredAssetType;
  return {
    id: Number(row.id),
    revision: Number(row.revision || 0),
    batchId: batchPath,
    batchName: batchParts.slice(-2).join(" · ") || "Unsorted import",
    name,
    relPath,
    thumbnailUrl: text(row.preview_url) || `/admin/nas-imports/${row.id}/preview`,
    mediaUrl: text(row.media_url),
    status,
    confidence: row.confidence == null ? null : Number(row.confidence),
    reason: text(row.reason) || (status === "pending" ? "尚未生成建议。" : ""),
    error: text(row.error) || undefined,
    sku: text(row.final_sku) || text(row.suggested_sku),
    englishName: text(row.final_english_name) || text(row.suggested_english_name),
    driveFolder: text(row.final_drive_folder) || text(row.suggested_drive_folder),
    driveName: text(row.final_drive_name) || text(row.suggested_drive_name) || name,
    assetType: (assetTypes.has(finalAssetType) ? finalAssetType : "other") as PendingImport["assetType"],
    setCode: text(row.final_set_code) || text(row.catalog_set_code),
    categoryId: text(row.final_category_id) || (text(row.suggested_category_id) === "UNKNOWN" ? "" : text(row.suggested_category_id)),
    categoryTags: (text(row.final_category_tags) || text(row.suggested_category_tags)).split("|").filter(Boolean),
    themes: (Number(row.themes_updated) ? text(row.final_themes) : text(row.catalog_themes)).split("|").filter(Boolean),
    categoryConfidence: Number(row.category_confidence || 0),
    categorySource: text(row.category_source),
    categoryReason: text(row.category_reason) || "尚未生成分类建议。",
    categoryNeedsReview: Boolean(Number(row.category_needs_review)),
    discoveredAt: formatDate(row.created_at),
  };
}

export function mapImportJob(row: Record<string, unknown>): ImportJob {
  const allowedStatuses = new Set(["queued", "running", "completed", "partial", "failed"]);
  const allowedItemStatuses = new Set(["queued", "uploading", "completed", "error"]);
  const items = Array.isArray(row.items) ? row.items as Array<Record<string, unknown>> : [];
  return {
    id: text(row.id),
    batchId: text(row.batch_id),
    batchName: text(row.batch_name) || "入库任务",
    status: (allowedStatuses.has(text(row.status)) ? text(row.status) : "queued") as ImportJob["status"],
    progress: Math.max(0, Math.min(100, Number(row.progress || 0))),
    total: Number(row.total || items.length),
    completed: Number(row.completed || 0),
    failed: Number(row.failed || 0),
    createdBy: text(row.created_by_name) || "System",
    createdAt: formatDate(row.created_at),
    finishedAt: timestamp(row.finished_at || row.updated_at),
    dismissedAt: timestamp(row.dismissed_at),
    items: items.map((item) => ({
      importId: Number(item.import_id),
      name: text(item.name),
      relPath: text(item.rel_path),
      status: (allowedItemStatuses.has(text(item.status)) ? text(item.status) : "queued") as ImportJob["items"][number]["status"],
      progress: Math.max(0, Math.min(100, Number(item.progress || 0))),
      stage: text(item.stage) || "queued",
      error: text(item.error),
    })),
  };
}

function mapOverview(payload: RawOverview): AdminOverview {
  return {
    imports: payload.imports.map(mapImport),
    importTotal: Number(payload.import_total || 0),
    importBatchTotal: Number(payload.import_batch_total || 0),
    importPage: Number(payload.import_page || 1),
    importPageSize: Number(payload.import_page_size || 6),
    importPages: Math.max(1, Number(payload.import_pages || 1)),
    importView: payload.import_view === "disabled" ? "disabled" : "active",
    activeImportTotal: Number(payload.active_import_total || 0),
    disabledImportTotal: Number(payload.disabled_import_total || 0),
    importStatusCounts: {
      pending: Number(payload.import_status_counts?.pending || 0),
      suggested: Number(payload.import_status_counts?.suggested || 0),
      error: Number(payload.import_status_counts?.error || 0),
      rejected: Number(payload.import_status_counts?.rejected || 0),
    },
    users: payload.users.map((user) => ({
      id: user.id,
      email: user.email,
      name: user.name,
      role: payload.role_labels[user.role] || user.role,
      permissionMode: user.permission_mode === "allowlist" ? "allowlist" : "role_default",
      disabled: Boolean(Number(user.disabled || 0)),
      createdAt: formatDate(user.created_at),
      expiresAt: user.expires_at ? formatDate(user.expires_at) : "",
    })),
    rules: payload.rules.map((rule) => ({
      id: rule.id,
      role: payload.role_labels[rule.role] || rule.role,
      scope: payload.scope_labels[rule.scope] || rule.scope,
      value: rule.value,
      createdAt: formatDate(rule.created_at),
    })),
    userGrants: (payload.user_grants || []).map((grant) => ({
      id: grant.id,
      userId: grant.user_id,
      userName: grant.name,
      userEmail: grant.email,
      scope: payload.scope_labels[grant.scope] || grant.scope,
      value: grant.value,
      createdAt: formatDate(grant.created_at),
    })),
    canManageAccess: Boolean(payload.can_manage_access),
    editLogs: payload.edit_logs.map((row) => ({
      id: Number(row.id),
      material: `${text(row.source_name)}${row.rel_path ? ` · ${text(row.rel_path)}` : ""}`,
      field: text(row.field),
      before: text(row.previous_value) || text(row.suggested_value),
      after: text(row.new_value),
      editor: text(row.editor) || "System",
      createdAt: formatDate(row.created_at),
    })),
    uploadHistory: payload.upload_history.map((row) => ({
      id: Number(row.id),
      sku: text(row.final_sku) || text(row.suggested_sku),
      name: text(row.final_drive_name) || text(row.name),
      destination: text(row.final_drive_folder),
      operator: text(row.approver) || "System",
      createdAt: formatDate(row.approved_at),
      thumbnailUrl: `/admin/nas-imports/${row.id}/preview`,
    })),
    syncStatus: payload.sync_status ? {
      state: payload.sync_status.state,
      message: payload.sync_status.message,
      rootId: payload.sync_status.root_id,
      fileCount: payload.sync_status.file_count,
      startedAt: formatDate(payload.sync_status.started_at),
      finishedAt: formatDate(payload.sync_status.finished_at),
    } : null,
    permissionValues: payload.permission_values,
    categoryOptions: (payload.category_options || []).map(mapCategoryOption),
    categoryTagOptions: (payload.category_tag_options || []).map(mapCategoryTagOption),
    themeOptions: (payload.theme_options || []).map((row) => ({ id: text(row.id), label: text(row.label) })),
    messageCount: Number(payload.message_count || 0),
    source: "api",
  };
}

export async function loadAdminOverview(importPage = 1, importPageSize = 6, importView: ImportView = "active"): Promise<AdminOverview> {
  if (!apiEnabled()) {
    const demoImports = importView === "disabled"
      ? initialPendingImports.filter((item) => item.status === "rejected")
      : initialPendingImports.filter((item) => item.status !== "rejected");
    return {
      imports: demoImports,
      importTotal: demoImports.length,
      importBatchTotal: new Set(demoImports.map((item) => item.batchId)).size,
      importPage: 1,
      importPageSize,
      importPages: 1,
      importView,
      activeImportTotal: initialPendingImports.filter((item) => item.status !== "rejected").length,
      disabledImportTotal: initialPendingImports.filter((item) => item.status === "rejected").length,
      importStatusCounts: {
        pending: initialPendingImports.filter((item) => item.status === "pending").length,
        suggested: initialPendingImports.filter((item) => item.status === "suggested").length,
        error: initialPendingImports.filter((item) => item.status === "error").length,
        rejected: initialPendingImports.filter((item) => item.status === "rejected").length,
      },
      users: initialUsers,
      rules: initialRules,
      userGrants: [],
      canManageAccess: true,
      editLogs: editLogs,
      uploadHistory: uploadHistory,
      syncStatus: null,
      permissionValues: demoPermissionValues,
      categoryOptions: demoCategoryOptions,
      categoryTagOptions: demoCategoryTagOptions,
      themeOptions: demoThemeOptions,
      messageCount: 0,
      source: "demo",
    };
  }
  const query = new URLSearchParams({
    import_page: String(importPage),
    import_page_size: String(importPageSize),
    import_view: importView,
  });
  const response = await fetch(`/api/admin/overview?${query}`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error("登录已过期，请重新登录。");
    if (response.status === 403) throw new Error("当前账号没有管理后台权限。");
    throw new Error(`管理后台数据加载失败（${response.status}）`);
  }
  return mapOverview(await response.json() as RawOverview);
}

export async function loadAdminNotificationCount(): Promise<number> {
  if (!apiEnabled()) {
    return initialPendingImports.filter((item) => item.status !== "rejected").length;
  }
  const response = await fetch("/api/admin/notifications", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(`通知读取失败（${response.status}）`);
  const payload = await response.json() as { pending_count?: number };
  return Math.max(0, Number(payload.pending_count || 0));
}

export async function loadImportJobs(): Promise<ImportJob[]> {
  if (!apiEnabled()) {
    const loadedAt = Date.now();
    return demoImportJobs.map((job) => ({
      ...job,
      finishedAt: job.status === "completed" ? loadedAt : job.finishedAt,
      items: job.items.map((item) => ({ ...item })),
    }));
  }
  const response = await fetch("/api/admin/import-jobs?limit=100", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(`入库进度读取失败（${response.status}）`);
  const payload = await response.json() as { jobs?: Array<Record<string, unknown>> };
  return (payload.jobs || []).map(mapImportJob);
}

export async function loadCustomerAccess(): Promise<CustomerAccessOverview> {
  if (!apiEnabled()) {
    return {
      users: demoCustomerAccess.users.map((user) => ({ ...user })),
      salespeople: demoCustomerAccess.salespeople.map((salesperson) => ({ ...salesperson })),
      rules: demoCustomerAccess.rules.map((rule) => ({ ...rule })),
      userGrants: demoCustomerAccess.userGrants.map((grant) => ({ ...grant })),
      permissionValues: demoPermissionValues,
    };
  }
  const response = await fetch("/api/admin/access-control", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(`客户权限数据加载失败（${response.status}）`);
  const payload = await response.json() as RawCustomerAccessOverview;
  return {
    users: payload.users.map((user) => ({
      id: Number(user.id),
      email: user.email,
      name: user.name,
      role: payload.role_labels[user.role] || user.role,
      permissionMode: user.permission_mode === "allowlist" ? "allowlist" : "role_default",
      disabled: Boolean(Number(user.disabled || 0)),
      createdAt: formatDate(user.created_at),
      expiresAt: user.expires_at ? formatDate(user.expires_at) : "",
      createdByUserId: user.created_by_user_id == null ? null : Number(user.created_by_user_id),
      createdByName: text(user.created_by_name),
    })),
    salespeople: (payload.salespeople || []).map((salesperson) => ({
      id: Number(salesperson.id),
      email: salesperson.email,
      name: salesperson.name,
      role: salesperson.role,
      disabled: Boolean(Number(salesperson.disabled || 0)),
    })),
    rules: payload.rules.map((rule) => ({
      id: Number(rule.id),
      role: payload.role_labels[rule.role] || rule.role,
      scope: payload.scope_labels[rule.scope] || rule.scope,
      value: rule.value,
      createdAt: formatDate(rule.created_at),
    })),
    userGrants: payload.user_grants.map((grant) => ({
      id: Number(grant.id),
      userId: Number(grant.user_id),
      userName: grant.name,
      userEmail: grant.email,
      scope: payload.scope_labels[grant.scope] || grant.scope,
      value: grant.value,
      createdAt: formatDate(grant.created_at),
    })),
    permissionValues: payload.permission_values,
  };
}

export async function loadAdminMessages(q = ""): Promise<{ messages: AdminMessage[]; total: number }> {
  if (!apiEnabled()) return { messages: [], total: 0 };
  const query = new URLSearchParams({ q, limit: "200", offset: "0" });
  const response = await fetch(`/api/admin/messages?${query}`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(`客户留言加载失败（${response.status}）`);
  const payload = await response.json() as { messages: Array<Record<string, unknown>>; total: number };
  return {
    messages: (payload.messages || []).map((row) => ({
      id: Number(row.id),
      sku: text(row.sku),
      productName: text(row.product_name),
      body: text(row.body),
      userName: text(row.user_name),
      userEmail: text(row.user_email),
      createdAt: formatDate(row.created_at),
    })),
    total: Number(payload.total || 0),
  };
}

export async function postAdminAction(path: string, data: Record<string, string | number | boolean | Array<string | number>> = {}) {
  if (!apiEnabled()) return { mode: "demo" as const };

  const formData = new FormData();
  Object.entries(data).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((item) => formData.append(key, String(item)));
    else formData.append(key, String(value));
  });
  const response = await fetch(path, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!response.ok) {
    let detail = "";
    try {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const payload = await response.json() as { detail?: unknown };
        detail = typeof payload.detail === "string" ? payload.detail.trim() : "";
      } else {
        detail = (await response.text()).trim();
      }
    } catch {
      detail = "";
    }
    throw new Error(detail || `管理操作失败（${response.status}）`);
  }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => undefined) as unknown
    : undefined;
  return { mode: "api" as const, data: payload };
}

export async function createAdminCategory(data: {
  group: string;
  labelEn: string;
  labelZh?: string;
}): Promise<CategoryOption> {
  if (!apiEnabled()) {
    const id = `CUSTOM_${data.labelEn.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "")}`;
    return { id, group: data.group, labelEn: data.labelEn, labelZh: data.labelZh || "" };
  }
  const formData = new FormData();
  formData.append("group", data.group);
  formData.append("label_en", data.labelEn);
  formData.append("label_zh", data.labelZh || "");
  const response = await fetch("/api/admin/categories", {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(text(payload.detail) || `新增分类失败（${response.status}）`);
  }
  return mapCategoryOption(payload);
}

export async function createAdminTheme(label: string): Promise<ThemeOption> {
  if (!apiEnabled()) {
    return {
      id: `CUSTOM_${label.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "")}`,
      label,
    };
  }
  const formData = new FormData();
  formData.append("label", label);
  const response = await fetch("/api/admin/themes", {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(text(payload.detail) || `新增主题失败（${response.status}）`);
  }
  return { id: text(payload.id), label: text(payload.label) };
}

export async function loadAdminProducts(q: string, page: number, pageSize = 40): Promise<AdminProductPage> {
  if (!apiEnabled()) {
    const needle = q.trim().toLowerCase();
    const filtered = mockProducts.filter((product) => !needle || [product.sku, product.name, product.brand, product.category, product.setCode]
      .join(" ").toLowerCase().includes(needle));
    const products = filtered.slice((page - 1) * pageSize, page * pageSize).map((product) => ({
      sku: product.sku,
      englishName: product.name,
      chineseName: "",
      brand: product.brand,
      category: product.category,
      categoryId: "",
      categoryZh: "",
      categoryTags: [],
      categoryConfidence: 0,
      categorySource: "demo",
      categoryStatus: "unclassified" as const,
      categoryReason: "",
      setCode: product.setCode || "",
      themes: (product.themes || []).flatMap((label) => demoThemeOptions.filter((item) => item.label === label).map((item) => item.id)),
      fileCount: product.assetCount ?? product.assets.length,
      modifiedTime: product.updatedAt,
    }));
    return {
      products,
      total: filtered.length,
      page,
      pageSize,
      setCodes: [],
      categoryOptions: demoCategoryOptions,
      categoryTagOptions: demoCategoryTagOptions,
      themeOptions: demoThemeOptions,
      source: "demo",
    };
  }
  const query = new URLSearchParams({ q, page: String(page), page_size: String(pageSize) });
  const response = await fetch(`/api/admin/products?${query}`, { credentials: "include" });
  if (!response.ok) throw new Error(`产品数据加载失败（${response.status}）`);
  const payload = await response.json() as {
    products: Array<Record<string, unknown>>;
    total: number;
    page: number;
    page_size: number;
    set_codes: string[];
    category_options: Array<Record<string, unknown>>;
    category_tag_options: Array<Record<string, unknown>>;
    theme_options: Array<Record<string, unknown>>;
  };
  return {
    products: payload.products.map((row) => ({
      sku: text(row.sku),
      englishName: text(row.english_name),
      chineseName: text(row.chinese_name),
      brand: text(row.brand),
      category: text(row.category),
      categoryId: text(row.category_id),
      categoryZh: text(row.category_zh),
      categoryTags: text(row.category_tags).split("|").filter(Boolean),
      categoryConfidence: Number(row.category_confidence || 0),
      categorySource: text(row.category_source),
      categoryStatus: (["verified", "needs_review"].includes(text(row.category_status))
        ? text(row.category_status)
        : "unclassified") as "verified" | "needs_review" | "unclassified",
      categoryReason: text(row.category_reason),
      setCode: text(row.set_code),
      themes: text(row.themes).split("|").filter(Boolean),
      fileCount: Number(row.file_count || 0),
      modifiedTime: formatDate(row.modified_time),
    })),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
    setCodes: payload.set_codes || [],
    categoryOptions: (payload.category_options || []).map(mapCategoryOption),
    categoryTagOptions: (payload.category_tag_options || []).map(mapCategoryTagOption),
    themeOptions: (payload.theme_options || []).map((row) => ({ id: text(row.id), label: text(row.label) })),
    source: "api",
  };
}

export async function updateAdminProductMetadata(data: {
  skus: string[];
  q: string;
  applyAll: boolean;
  setCode?: string;
  categoryId?: string;
  categoryTags?: string[];
  themes?: string[];
  updateSet?: boolean;
  updateCategory?: boolean;
  updateThemes?: boolean;
}) {
  return postAdminAction("/api/admin/products/bulk-metadata", {
    skus: data.skus,
    q: data.q,
    apply_all: data.applyAll,
    set_code: data.setCode || "",
    category_id: data.categoryId || "",
    category_tags: (data.categoryTags || []).join("|"),
    themes: (data.themes || []).join("|"),
    update_set: Boolean(data.updateSet),
    update_category: Boolean(data.updateCategory),
    update_themes: Boolean(data.updateThemes),
  });
}

export async function postAdminFile(path: string, file: File) {
  if (!apiEnabled()) return { mode: "demo" as const };

  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(path, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!response.ok) throw new Error(`文件导入失败（${response.status}）`);
  return { mode: "api" as const };
}

export interface DriveFolderListing {
  path: string;
  folders: string[];
  exact: boolean;
}

export async function listDriveFolders(parentPath: string): Promise<DriveFolderListing | null> {
  if (!apiEnabled()) return null;
  const query = new URLSearchParams({ parent_path: parentPath });
  const response = await fetch(`/admin/drive-folders?${query}`, { credentials: "include" });
  if (!response.ok) throw new Error(`目录读取失败（${response.status}）`);
  const payload = await response.json() as { path: string; folders: Array<{ path: string }>; exact: boolean };
  return {
    path: payload.path,
    folders: payload.folders.map((folder) => folder.path),
    exact: payload.exact,
  };
}

export async function createDriveFolder(parentPath: string, name: string): Promise<string | null> {
  if (!apiEnabled()) return null;
  const formData = new FormData();
  formData.append("parent_path", parentPath);
  formData.append("name", name);
  const response = await fetch("/admin/drive-folders", {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!response.ok) throw new Error(`目录创建失败（${response.status}）`);
  const payload = await response.json() as { path: string };
  return payload.path;
}
