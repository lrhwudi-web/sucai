import { apiEnabled } from "../services/auth";
import type { OrganizationOverview, UserActivityDetail, UserMonitorOverview } from "./types";

interface RawOrganizationOverview {
  departments: Array<{
    id: string | number;
    name: string;
    parent_id: string | number;
    depth: number;
    member_count: number;
  }>;
  members: Array<{
    user_id: string;
    name: string;
    department_ids: Array<string | number>;
    department_names: string[];
    role: string;
    is_super_admin: boolean;
    admin_granted: boolean;
    has_local_account: boolean;
  }>;
  stats: {
    departments: number;
    members: number;
    admins: number;
    super_admins: number;
  };
  synced_at: string;
}

interface RawMonitorUser {
  id: number;
  email: string;
  name: string;
  role: string;
  created_at: string;
  last_login_at: string | null;
  login_count: number;
  original_open_count: number;
  download_count: number;
  event_count: number;
}

interface RawUserMonitorOverview {
  users: RawMonitorUser[];
  stats: {
    users: number;
    logged_in_users: number;
    logins: number;
    original_opens: number;
    downloads: number;
    events: number;
  };
}

interface RawUserActivityDetail {
  user: Pick<RawMonitorUser, "id" | "email" | "name" | "role" | "created_at">;
  events: Array<{
    id: number;
    event_type: "login" | "original_open" | "download" | "drive_export";
    sku: string;
    file_id: string;
    file_name: string;
    detail: string;
    created_at: string;
  }>;
}

const ORGANIZATION_CACHE_KEY = "kairay.superAdmin.organization.v1";

export function loadCachedOrganizationAccess(): OrganizationOverview | null {
  try {
    const value = window.localStorage.getItem(ORGANIZATION_CACHE_KEY);
    if (!value) return null;
    const cached = JSON.parse(value) as OrganizationOverview;
    return Array.isArray(cached.departments) && Array.isArray(cached.members) && cached.stats
      ? cached
      : null;
  } catch {
    return null;
  }
}

function saveCachedOrganizationAccess(overview: OrganizationOverview) {
  try {
    window.localStorage.setItem(ORGANIZATION_CACHE_KEY, JSON.stringify(overview));
  } catch {
    // The server-side cache still avoids a DingTalk round trip when storage is unavailable.
  }
}

async function responseError(response: Response, fallback: string) {
  try {
    const payload = await response.json() as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

export async function loadOrganizationAccess(refresh = false): Promise<OrganizationOverview> {
  if (!apiEnabled()) {
    return {
      departments: [
        { id: "1", name: "全部组织", parentId: "", depth: 0, memberCount: 4 },
        { id: "2", name: "信息技术部", parentId: "1", depth: 1, memberCount: 1 },
        { id: "3", name: "市场部", parentId: "1", depth: 1, memberCount: 3 },
      ],
      members: [
        { userId: "demo-it", name: "刘芮华", departmentIds: ["2"], departmentNames: ["信息技术部"], role: "super_admin", isSuperAdmin: true, adminGranted: false, hasLocalAccount: true },
        { userId: "demo-market", name: "陈晓", departmentIds: ["3"], departmentNames: ["市场部"], role: "admin", isSuperAdmin: false, adminGranted: true, hasLocalAccount: true },
        { userId: "demo-staff", name: "周宁", departmentIds: ["3"], departmentNames: ["市场部"], role: "internal_staff", isSuperAdmin: false, adminGranted: false, hasLocalAccount: false },
      ],
      stats: { departments: 2, members: 3, admins: 1, superAdmins: 1 },
      syncedAt: new Date().toISOString(),
    };
  }
  const response = await fetch(refresh ? "/api/super-admin/organization/refresh" : "/api/super-admin/organization", {
    method: refresh ? "POST" : "GET",
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await responseError(response, "组织架构加载失败。"));
  const payload = await response.json() as RawOrganizationOverview;
  const overview = {
    departments: payload.departments.map((item) => ({
      id: String(item.id),
      name: item.name,
      parentId: String(item.parent_id || ""),
      depth: Number(item.depth || 0),
      memberCount: Number(item.member_count || 0),
    })),
    members: payload.members.map((item) => ({
      userId: item.user_id,
      name: item.name,
      departmentIds: item.department_ids.map(String),
      departmentNames: item.department_names,
      role: item.role,
      isSuperAdmin: Boolean(item.is_super_admin),
      adminGranted: Boolean(item.admin_granted),
      hasLocalAccount: Boolean(item.has_local_account),
    })),
    stats: {
      departments: Number(payload.stats.departments || 0),
      members: Number(payload.stats.members || 0),
      admins: Number(payload.stats.admins || 0),
      superAdmins: Number(payload.stats.super_admins || 0),
    },
    syncedAt: payload.synced_at,
  };
  saveCachedOrganizationAccess(overview);
  return overview;
}

export async function setOrganizationAdmin(userId: string, enabled: boolean) {
  if (!apiEnabled()) return;
  const form = new FormData();
  form.set("enabled", String(enabled));
  const response = await fetch(`/api/super-admin/organization/${encodeURIComponent(userId)}/admin`, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await responseError(response, "管理员权限更新失败。"));
}

export async function loadUserMonitor(): Promise<UserMonitorOverview> {
  if (!apiEnabled()) {
    return {
      users: [],
      stats: { users: 0, loggedInUsers: 0, logins: 0, originalOpens: 0, downloads: 0, events: 0 },
    };
  }
  const response = await fetch("/api/super-admin/user-monitor", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await responseError(response, "用户监控数据加载失败。"));
  const payload = await response.json() as RawUserMonitorOverview;
  return {
    users: payload.users.map((item) => ({
      id: Number(item.id),
      email: item.email,
      name: item.name,
      role: item.role,
      createdAt: item.created_at,
      lastLoginAt: item.last_login_at || "",
      loginCount: Number(item.login_count || 0),
      originalOpenCount: Number(item.original_open_count || 0),
      downloadCount: Number(item.download_count || 0),
      eventCount: Number(item.event_count || 0),
    })),
    stats: {
      users: Number(payload.stats.users || 0),
      loggedInUsers: Number(payload.stats.logged_in_users || 0),
      logins: Number(payload.stats.logins || 0),
      originalOpens: Number(payload.stats.original_opens || 0),
      downloads: Number(payload.stats.downloads || 0),
      events: Number(payload.stats.events || 0),
    },
  };
}

export async function loadUserActivity(userId: number): Promise<UserActivityDetail> {
  const response = await fetch(`/api/super-admin/user-monitor/${encodeURIComponent(userId)}`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await responseError(response, "用户操作记录加载失败。"));
  const payload = await response.json() as RawUserActivityDetail;
  return {
    user: {
      id: Number(payload.user.id),
      email: payload.user.email,
      name: payload.user.name,
      role: payload.user.role,
      createdAt: payload.user.created_at,
    },
    events: payload.events.map((item) => ({
      id: Number(item.id),
      eventType: item.event_type,
      sku: item.sku || "",
      fileId: item.file_id || "",
      fileName: item.file_name || "",
      detail: item.detail || "",
      createdAt: item.created_at,
    })),
  };
}
