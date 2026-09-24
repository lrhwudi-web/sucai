export type AdminSection = "pending" | "data" | "messages" | "permissions" | "orders" | "edits" | "history" | "sync";
export type ImportStatus = "pending" | "suggested" | "error" | "rejected";
export type ImportView = "active" | "disabled";

export interface CategoryOption {
  id: string;
  group: string;
  labelZh: string;
  labelEn: string;
}

export interface CategoryTagOption {
  id: string;
  labelZh: string;
  labelEn: string;
}

export interface ThemeOption {
  id: string;
  label: string;
}

export interface PendingImport {
  id: number;
  revision: number;
  batchId: string;
  batchName: string;
  name: string;
  relPath: string;
  thumbnailUrl: string;
  mediaUrl: string;
  status: ImportStatus;
  confidence: number | null;
  reason: string;
  error?: string;
  sku: string;
  englishName: string;
  driveFolder: string;
  driveName: string;
  assetType: "image" | "video" | "kol_ugc" | "ads" | "other";
  setCode: string;
  categoryId: string;
  categoryTags: string[];
  themes: string[];
  categoryConfidence: number;
  categorySource: string;
  categoryReason: string;
  categoryNeedsReview: boolean;
  discoveredAt: string;
}

export type ImportJobStatus = "queued" | "running" | "completed" | "partial" | "failed";
export type ImportJobItemStatus = "queued" | "uploading" | "completed" | "error";

export interface ImportJobItem {
  importId: number;
  name: string;
  relPath: string;
  status: ImportJobItemStatus;
  progress: number;
  stage: string;
  error: string;
}

export interface ImportJob {
  id: string;
  batchId: string;
  batchName: string;
  status: ImportJobStatus;
  progress: number;
  total: number;
  completed: number;
  failed: number;
  createdBy: string;
  createdAt: string;
  finishedAt: number | null;
  dismissedAt: number | null;
  items: ImportJobItem[];
}

export interface AdminProductRecord {
  sku: string;
  englishName: string;
  chineseName: string;
  brand: string;
  category: string;
  categoryId: string;
  categoryZh: string;
  categoryTags: string[];
  categoryConfidence: number;
  categorySource: string;
  categoryStatus: "verified" | "needs_review" | "unclassified";
  categoryReason: string;
  setCode: string;
  themes: string[];
  fileCount: number;
  modifiedTime: string;
}

export interface AdminProductPage {
  products: AdminProductRecord[];
  total: number;
  page: number;
  pageSize: number;
  setCodes: string[];
  categoryOptions: CategoryOption[];
  categoryTagOptions: CategoryTagOption[];
  themeOptions: ThemeOption[];
  source: "api" | "demo";
}

export interface AdminUser {
  id: number;
  email: string;
  name: string;
  role: string;
  permissionMode: "role_default" | "allowlist";
  disabled: boolean;
  expired?: boolean;
  createdAt: string;
  expiresAt?: string;
  createdByUserId?: number | null;
  createdByName?: string;
}

export interface SalespersonOption {
  id: number;
  email: string;
  name: string;
  role: string;
  disabled: boolean;
}

export interface PermissionRule {
  id: number;
  role: string;
  scope: string;
  value: string;
  createdAt: string;
}

export interface UserPermissionGrant {
  id: number;
  userId: number;
  userName: string;
  userEmail: string;
  scope: string;
  value: string;
  createdAt: string;
}

export interface EditLog {
  id: number;
  material: string;
  field: string;
  before: string;
  after: string;
  editor: string;
  createdAt: string;
}

export interface UploadRecord {
  id: number;
  sku: string;
  name: string;
  destination: string;
  operator: string;
  createdAt: string;
  thumbnailUrl: string;
}

export interface AdminMessage {
  id: number;
  sku: string;
  productName: string;
  body: string;
  userName: string;
  userEmail: string;
  createdAt: string;
}

export interface SyncStatus {
  state: string;
  message: string;
  rootId: string;
  fileCount: number;
  startedAt: string;
  finishedAt: string;
}

export interface AdminOverview {
  imports: PendingImport[];
  importTotal: number;
  importBatchTotal: number;
  importPage: number;
  importPageSize: number;
  importPages: number;
  importView: ImportView;
  activeImportTotal: number;
  disabledImportTotal: number;
  importStatusCounts: Record<ImportStatus, number>;
  users: AdminUser[];
  rules: PermissionRule[];
  userGrants: UserPermissionGrant[];
  canManageAccess: boolean;
  editLogs: EditLog[];
  uploadHistory: UploadRecord[];
  syncStatus: SyncStatus | null;
  permissionValues: Record<string, string[]>;
  categoryOptions: CategoryOption[];
  categoryTagOptions: CategoryTagOption[];
  themeOptions: ThemeOption[];
  messageCount: number;
  source: "api" | "demo";
}

export interface OrganizationDepartment {
  id: string;
  name: string;
  parentId: string;
  depth: number;
  memberCount: number;
}

export interface OrganizationMember {
  userId: string;
  name: string;
  departmentIds: string[];
  departmentNames: string[];
  role: "super_admin" | "admin" | "internal_staff" | string;
  isSuperAdmin: boolean;
  adminGranted: boolean;
  hasLocalAccount: boolean;
}

export interface OrganizationOverview {
  departments: OrganizationDepartment[];
  members: OrganizationMember[];
  stats: {
    departments: number;
    members: number;
    admins: number;
    superAdmins: number;
  };
  syncedAt: string;
}

export interface UserMonitorUser {
  id: number;
  email: string;
  name: string;
  role: string;
  createdAt: string;
  lastLoginAt: string;
  loginCount: number;
  originalOpenCount: number;
  downloadCount: number;
  eventCount: number;
}

export interface UserMonitorOverview {
  users: UserMonitorUser[];
  stats: {
    users: number;
    loggedInUsers: number;
    logins: number;
    originalOpens: number;
    downloads: number;
    events: number;
  };
}

export interface UserActivityEvent {
  id: number;
  eventType: "login" | "original_open" | "download" | "drive_export";
  sku: string;
  fileId: string;
  fileName: string;
  detail: string;
  createdAt: string;
}

export interface UserActivityDetail {
  user: Pick<UserMonitorUser, "id" | "email" | "name" | "role" | "createdAt">;
  events: UserActivityEvent[];
}

export interface CustomerAccessOverview {
  users: AdminUser[];
  salespeople: SalespersonOption[];
  rules: PermissionRule[];
  userGrants: UserPermissionGrant[];
  permissionValues: Record<string, string[]>;
}
