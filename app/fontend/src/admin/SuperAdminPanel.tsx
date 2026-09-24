import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwise,
  Buildings,
  ChartLineUp,
  CheckCircle,
  Database,
  LockKey,
  MagnifyingGlass,
  ShieldCheck,
  ShieldStar,
  SpinnerGap,
  UserCircle,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { loadCachedOrganizationAccess, loadOrganizationAccess, setOrganizationAdmin } from "./superAdminService";
import type { OrganizationOverview } from "./types";
import { UserMonitorWorkspace } from "./UserMonitorWorkspace";
import { AdminPanel } from "./AdminPanel";
import type { AuthUser } from "../services/auth";

interface SuperAdminPanelProps {
  user: AuthUser;
  onNotify: (message: string) => void;
}

function formatSyncTime(value: string) {
  if (!value) return "尚未同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function SuperAdminPanel({ user, onNotify }: SuperAdminPanelProps) {
  const [section, setSection] = useState<"materials" | "organization" | "monitor">("organization");
  const [overview, setOverview] = useState<OrganizationOverview | null>(() => loadCachedOrganizationAccess());
  const [loading, setLoading] = useState(() => !loadCachedOrganizationAccess());
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [departmentId, setDepartmentId] = useState("1");
  const [updatingUserId, setUpdatingUserId] = useState("");

  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    setError("");
    try {
      setOverview(await loadOrganizationAccess(force));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "组织架构加载失败。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!overview) refresh(false).catch(() => undefined);
  }, [overview, refresh]);

  const departmentScope = useMemo(() => {
    if (!overview || departmentId === "1") return new Set(overview?.departments.map((item) => item.id) || []);
    const scope = new Set([departmentId]);
    let expanded = true;
    while (expanded) {
      expanded = false;
      overview.departments.forEach((item) => {
        if (scope.has(item.parentId) && !scope.has(item.id)) {
          scope.add(item.id);
          expanded = true;
        }
      });
    }
    return scope;
  }, [departmentId, overview]);

  const visibleMembers = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return (overview?.members || []).filter((member) => {
      if (!member.departmentIds.some((id) => departmentScope.has(id))) return false;
      if (!needle) return true;
      return [member.name, ...member.departmentNames, member.role].join(" ").toLocaleLowerCase().includes(needle);
    });
  }, [departmentScope, overview, search]);

  const updateMember = async (userId: string, enabled: boolean, name: string) => {
    if (updatingUserId) return;
    setUpdatingUserId(userId);
    try {
      await setOrganizationAdmin(userId, enabled);
      await refresh(false);
      onNotify(enabled ? `已授予 ${name} 管理员权限` : `已撤销 ${name} 的管理员权限`);
    } catch (caught) {
      onNotify(caught instanceof Error ? caught.message : "管理员权限更新失败。");
    } finally {
      setUpdatingUserId("");
    }
  };

  return (
    <div className="super-admin-shell">
      <aside className="super-admin-nav-shell" aria-label="超级管理导航">
        <div className="super-admin-nav-title">
          <span>Super admin</span>
          <strong>超级管理中心</strong>
          <small>组织架构与权限治理</small>
        </div>
        <nav className="super-admin-section-nav">
          <button className={section === "materials" ? "is-active" : ""} type="button" onClick={() => setSection("materials")}><Database size={19} weight="fill" /><span>素材管理</span><em>后台</em></button>
          <button className={section === "organization" ? "is-active" : ""} type="button" onClick={() => setSection("organization")}><Buildings size={19} weight="fill" /><span>组织与权限</span><em>{overview?.stats.members || "—"}</em></button>
          <button className={section === "monitor" ? "is-active" : ""} type="button" onClick={() => setSection("monitor")}><ChartLineUp size={19} weight="fill" /><span>用户监控</span><em>日志</em></button>
        </nav>
        <div className="super-admin-policy-note">
          <ShieldStar size={22} weight="duotone" />
          <div><strong>超级管理员自动识别</strong><small>信息技术部成员由钉钉组织架构自动授予，不支持手工创建。</small></div>
        </div>
        <div className="admin-system-state">
          <span className="state-dot" />
          <div><strong>钉钉通讯录已连接</strong><small>最近同步 · {formatSyncTime(overview?.syncedAt || "")}</small></div>
        </div>
      </aside>

      <main className={`super-admin-main ${section === "materials" ? "is-materials" : ""}`}>
        {section === "materials" ? <AdminPanel user={user} search="" onNotify={onNotify} /> : section === "monitor" ? <UserMonitorWorkspace onNotify={onNotify} /> : (
        <>
        <header className="super-admin-heading">
          <div><span className="eyebrow">Organization access</span><h1>组织与权限</h1><p>从钉钉组织架构选择员工，授予或撤销素材管理后台的管理员权限。</p></div>
          <button className="button button-secondary" type="button" onClick={() => refresh(true)} disabled={loading}><ArrowsClockwise className={loading ? "is-spinning" : ""} size={18} weight="bold" /> 手动刷新</button>
        </header>

        {loading && !overview ? (
          <div className="super-admin-loading" role="status"><SpinnerGap className="is-spinning" size={28} weight="bold" /><strong>正在同步钉钉组织架构</strong><span>部门和员工权限会保持与钉钉一致。</span></div>
        ) : error && !overview ? (
          <div className="super-admin-loading is-error"><WarningCircle size={30} weight="duotone" /><strong>组织架构加载失败</strong><span>{error}</span><button className="button button-primary" onClick={() => refresh(true)}>手动刷新</button></div>
        ) : overview ? (
          <>
            <section className="super-admin-kpis" aria-label="组织权限概览">
              <div><span><Buildings size={18} weight="duotone" /> 部门</span><strong>{overview.stats.departments}</strong><small>钉钉组织节点</small></div>
              <div><span><UsersThree size={18} weight="duotone" /> 员工</span><strong>{overview.stats.members}</strong><small>当前可见成员</small></div>
              <div><span><ShieldCheck size={18} weight="duotone" /> 管理员</span><strong>{overview.stats.admins}</strong><small>手工授权</small></div>
              <div><span><ShieldStar size={18} weight="duotone" /> 超级管理员</span><strong>{overview.stats.superAdmins}</strong><small>信息技术部自动授予</small></div>
            </section>

            <section className="organization-access-card">
              <aside className="organization-tree">
                <div className="organization-panel-heading"><span><Buildings size={19} weight="duotone" /></span><div><strong>组织架构</strong><small>{overview.stats.departments} 个部门</small></div></div>
                <div className="organization-department-list">
                  {overview.departments.map((department) => (
                    <button
                      key={department.id}
                      className={departmentId === department.id ? "is-active" : ""}
                      style={{ "--department-indent": `${Math.max(0, department.depth) * 13}px` } as CSSProperties}
                      onClick={() => setDepartmentId(department.id)}
                    >
                      {department.id === "1" ? <Buildings size={17} weight="bold" /> : <UsersThree size={16} weight="bold" />}
                      <span>{department.name}</span><em>{department.id === "1" ? overview.stats.members : department.memberCount}</em>
                    </button>
                  ))}
                </div>
              </aside>

              <div className="organization-members">
                <header className="organization-members-toolbar">
                  <div><strong>{overview.departments.find((item) => item.id === departmentId)?.name || "全部组织"}</strong><small>{visibleMembers.length} 位成员</small></div>
                  <label><MagnifyingGlass size={18} weight="bold" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索员工或部门" /></label>
                </header>
                <div className="organization-member-table">
                  <div className="organization-member-row is-head"><span>员工</span><span>所属部门</span><span>当前权限</span><span>管理员授权</span></div>
                  {visibleMembers.map((member) => {
                    const isUpdating = updatingUserId === member.userId;
                    const isLegacyAdmin = member.role === "admin" && !member.adminGranted;
                    return (
                      <div className="organization-member-row" key={member.userId}>
                        <span className="organization-member-name"><i>{member.name.slice(0, 1)}</i><span><strong>{member.name}</strong><small>{member.hasLocalAccount ? "已登录素材库" : "尚未登录素材库"}</small></span></span>
                        <span className="organization-member-departments">{member.departmentNames.length ? member.departmentNames.map((name) => <em key={name}>{name}</em>) : <small>未分配部门</small>}</span>
                        <span><mark className={`role-chip is-${member.role}`}>{member.isSuperAdmin ? "超级管理员" : member.role === "admin" ? "管理员" : "普通员工"}</mark></span>
                        <span className="organization-member-action">
                          {member.isSuperAdmin ? (
                            <button className="admin-access-button is-locked" disabled><LockKey size={16} weight="bold" /> 自动授予</button>
                          ) : isLegacyAdmin ? (
                            <button className="admin-access-button is-locked" disabled><CheckCircle size={16} weight="bold" /> 已有权限</button>
                          ) : (
                            <button
                              className={member.adminGranted ? "admin-access-button is-granted" : "admin-access-button"}
                              disabled={Boolean(updatingUserId)}
                              aria-pressed={member.adminGranted}
                              onClick={() => updateMember(member.userId, !member.adminGranted, member.name)}
                            >
                              {isUpdating ? <SpinnerGap className="is-spinning" size={16} weight="bold" /> : member.adminGranted ? <CheckCircle size={16} weight="fill" /> : <UserCircle size={16} weight="bold" />}
                              {isUpdating ? "正在更新" : member.adminGranted ? "撤销管理员" : "设为管理员"}
                            </button>
                          )}
                        </span>
                      </div>
                    );
                  })}
                  {!visibleMembers.length && <div className="organization-empty"><UsersThree size={28} weight="duotone" /><strong>没有找到员工</strong><span>试试切换部门或清空搜索条件。</span></div>}
                </div>
              </div>
            </section>
          </>
        ) : null}
        </>
        )}
      </main>
    </div>
  );
}
