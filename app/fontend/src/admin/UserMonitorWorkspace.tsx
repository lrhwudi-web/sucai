import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwise,
  ClockCounterClockwise,
  DownloadSimple,
  Eye,
  FolderOpen,
  MagnifyingGlass,
  SignIn,
  SpinnerGap,
  UserCircle,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { loadUserActivity, loadUserMonitor } from "./superAdminService";
import type { UserActivityDetail, UserActivityEvent, UserMonitorOverview } from "./types";

interface UserMonitorWorkspaceProps {
  onNotify: (message: string) => void;
}

const roleLabels: Record<string, string> = {
  super_admin: "超级管理员",
  admin: "管理员",
  internal_staff: "内部员工",
  overseas_customer: "海外客户",
  domestic_customer: "国内客户",
  service_provider: "服务商",
};

const eventLabels: Record<UserActivityEvent["eventType"], string> = {
  login: "登录系统",
  original_open: "查看原图",
  download: "下载素材",
  drive_export: "打开 Drive 素材",
};

function dateValue(value: string) {
  if (!value) return null;
  const normalized = value.includes("T") || value.endsWith("Z") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value: string, fallback = "从未登录") {
  const date = dateValue(value);
  if (!date) return value || fallback;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function EventIcon({ type }: { type: UserActivityEvent["eventType"] }) {
  if (type === "login") return <SignIn size={18} weight="duotone" />;
  if (type === "original_open") return <Eye size={18} weight="duotone" />;
  if (type === "drive_export") return <FolderOpen size={18} weight="duotone" />;
  return <DownloadSimple size={18} weight="duotone" />;
}

export function UserMonitorWorkspace({ onNotify }: UserMonitorWorkspaceProps) {
  const [overview, setOverview] = useState<UserMonitorOverview | null>(null);
  const [detail, setDetail] = useState<UserActivityDetail | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const nextOverview = await loadUserMonitor();
      setOverview(nextOverview);
      if (selectedUserId) {
        setDetail(await loadUserActivity(selectedUserId));
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "用户监控数据加载失败。";
      setError(message);
      onNotify(message);
    } finally {
      setLoading(false);
    }
  }, [onNotify, selectedUserId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const visibleUsers = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    if (!needle) return overview?.users || [];
    return (overview?.users || []).filter((user) => (
      [user.name, user.email, roleLabels[user.role] || user.role]
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle)
    ));
  }, [overview, search]);

  const selectUser = async (userId: number) => {
    setSelectedUserId(userId);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await loadUserActivity(userId));
    } catch (caught) {
      onNotify(caught instanceof Error ? caught.message : "用户操作记录加载失败。");
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <>
      <header className="super-admin-heading">
        <div>
          <span className="eyebrow">User activity</span>
          <h1>用户监控</h1>
          <p>查看账号登录、原图查看和素材下载记录。只有超级管理员可以访问。</p>
        </div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={loading}>
          <ArrowsClockwise className={loading ? "is-spinning" : ""} size={18} weight="bold" /> 刷新记录
        </button>
      </header>

      {loading && !overview ? (
        <div className="super-admin-loading" role="status">
          <SpinnerGap className="is-spinning" size={28} weight="bold" />
          <strong>正在加载用户活动</strong>
          <span>正在汇总登录、原图查看与下载记录。</span>
        </div>
      ) : error && !overview ? (
        <div className="super-admin-loading is-error">
          <WarningCircle size={30} weight="duotone" />
          <strong>用户监控加载失败</strong>
          <span>{error}</span>
          <button className="button button-primary" onClick={() => void refresh()}>重新加载</button>
        </div>
      ) : overview ? (
        <>
          <section className="super-admin-kpis user-monitor-kpis" aria-label="用户活动概览">
            <div><span><UsersThree size={18} weight="duotone" /> 系统账号</span><strong>{overview.stats.users}</strong><small>{overview.stats.loggedInUsers} 人已有登录记录</small></div>
            <div><span><SignIn size={18} weight="duotone" /> 登录次数</span><strong>{overview.stats.logins}</strong><small>成功登录才会记录</small></div>
            <div><span><Eye size={18} weight="duotone" /> 查看原图</span><strong>{overview.stats.originalOpens}</strong><small>点击 Open original</small></div>
            <div><span><DownloadSimple size={18} weight="duotone" /> 素材下载</span><strong>{overview.stats.downloads}</strong><small>含下载与打开 Drive</small></div>
          </section>

          <section className="user-monitor-card">
            <aside className="user-monitor-users">
              <header>
                <div><strong>账号列表</strong><small>{visibleUsers.length} 个账号</small></div>
                <label><MagnifyingGlass size={17} weight="bold" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名、邮箱或角色" /></label>
              </header>
              <div className="user-monitor-user-list">
                {visibleUsers.map((user) => (
                  <button
                    key={user.id}
                    className={selectedUserId === user.id ? "user-monitor-user is-active" : "user-monitor-user"}
                    type="button"
                    onClick={() => void selectUser(user.id)}
                  >
                    <i>{(user.name || user.email || "?").slice(0, 1).toLocaleUpperCase()}</i>
                    <span>
                      <strong>{user.name || user.email}</strong>
                      <small>{user.email}</small>
                      <em><ClockCounterClockwise size={12} weight="bold" /> {formatDate(user.lastLoginAt)}</em>
                    </span>
                    <mark>{user.eventCount}</mark>
                  </button>
                ))}
                {!visibleUsers.length && <div className="user-monitor-empty"><UsersThree size={26} weight="duotone" /><strong>没有匹配账号</strong><span>清空搜索条件后再试。</span></div>}
              </div>
            </aside>

            <div className="user-activity-panel">
              {detailLoading ? (
                <div className="user-monitor-empty"><SpinnerGap className="is-spinning" size={28} weight="bold" /><strong>正在加载操作记录</strong></div>
              ) : detail ? (
                <>
                  <header className="user-activity-heading">
                    <div className="user-activity-identity"><i>{(detail.user.name || detail.user.email).slice(0, 1).toLocaleUpperCase()}</i><span><strong>{detail.user.name || detail.user.email}</strong><small>{detail.user.email}</small></span></div>
                    <mark className={`role-chip is-${detail.user.role}`}>{roleLabels[detail.user.role] || detail.user.role}</mark>
                  </header>
                  <div className="user-activity-timeline">
                    {detail.events.map((event) => (
                      <article className={`user-activity-event is-${event.eventType}`} key={event.id}>
                        <i><EventIcon type={event.eventType} /></i>
                        <div>
                          <strong>{eventLabels[event.eventType]}</strong>
                          <span>{event.fileName || (event.sku ? `SKU ${event.sku}` : event.detail === "dingtalk" ? "钉钉登录" : event.detail === "password" ? "账号密码登录" : "系统操作")}</span>
                          {event.fileName && event.sku ? <small>SKU {event.sku}</small> : null}
                        </div>
                        <time>{formatDate(event.createdAt, "")}</time>
                      </article>
                    ))}
                    {!detail.events.length && <div className="user-monitor-empty"><ClockCounterClockwise size={28} weight="duotone" /><strong>暂无操作记录</strong><span>该用户尚未登录或使用素材。</span></div>}
                  </div>
                </>
              ) : (
                <div className="user-monitor-empty is-prompt"><UserCircle size={36} weight="duotone" /><strong>选择一个账号</strong><span>点击左侧用户，查看其登录、原图查看和下载记录。</span></div>
              )}
            </div>
          </section>
        </>
      ) : null}
    </>
  );
}
