import { useEffect, useState } from "react";
import { SpinnerGap, UserPlus, UsersThree, X } from "@phosphor-icons/react";
import { postAdminAction } from "./adminService";
import type { AdminUser } from "./types";

interface CustomerAccountsPanelProps {
  users: AdminUser[];
  onRefresh: () => Promise<void>;
  onNotify: (message: string) => void;
}

export function CustomerAccountsPanel({ users, onRefresh, onNotify }: CustomerAccountsPanelProps) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, submitting]);

  const createAccount = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSubmitting(true);
    try {
      await postAdminAction("/admin/users", Object.fromEntries(data.entries()) as Record<string, string>);
      await onRefresh();
      setOpen(false);
      onNotify("客户账号已创建");
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "客户账号创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="admin-section">
      <header className="admin-page-heading">
        <div>
          <span className="eyebrow">Customer accounts</span>
          <h1>客户账号管理</h1>
          <p>创建可登录素材库的客户账号。管理员与超级管理员权限不在此处设置。</p>
        </div>
        <button className="button button-primary" onClick={() => setOpen(true)}>
          <UserPlus size={18} weight="bold" /> 创建客户账号
        </button>
      </header>

      <div className="admin-content-card">
        <div className="admin-card-heading">
          <div><UsersThree size={20} weight="duotone" /><span><strong>客户账号</strong><small>仅包含海外客户、国内客户和服务商</small></span></div>
          <em>{users.length} 个</em>
        </div>
        <div className="admin-data-table customer-accounts-table">
          <div className="admin-table-row is-head"><span>成员</span><span>邮箱</span><span>角色</span><span>创建时间</span></div>
          {users.map((user) => (
            <div className="admin-table-row" key={user.id}>
              <span className="member-cell"><i>{user.name.slice(0, 1).toUpperCase()}</i><b>{user.name}</b></span>
              <span>{user.email}</span>
              <span><mark>{user.role}</mark></span>
              <span>{user.createdAt}</span>
            </div>
          ))}
          {!users.length && <div className="admin-table-row customer-account-empty"><span>暂时没有客户账号</span><span /><span /><span /></div>}
        </div>
      </div>

      {open && (
        <div className="review-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) setOpen(false); }}>
          <section className="permission-modal" role="dialog" aria-modal="true" aria-labelledby="customer-account-modal-title">
            <header className="review-modal-heading">
              <div><span>Customer account</span><h2 id="customer-account-modal-title">创建客户账号</h2><small>管理员权限只能由超级管理员通过钉钉组织架构授予。</small></div>
              <button type="button" className="modal-icon-button" onClick={() => setOpen(false)} disabled={submitting} aria-label="关闭"><X size={20} weight="bold" /></button>
            </header>
            <div className="permission-modal-body">
              <form id="customer-account-form" className="admin-form-grid permission-modal-form" onSubmit={createAccount}>
                <label>邮箱<input type="email" name="email" required placeholder="name@company.com" autoFocus /></label>
                <label>姓名<input name="name" required placeholder="客户姓名" /></label>
                <label>角色<select name="role" defaultValue="overseas_customer"><option value="overseas_customer">海外客户</option><option value="domestic_customer">国内客户</option><option value="service_provider">服务商</option></select></label>
                <label>初始密码<input type="password" name="password" required minLength={8} placeholder="至少 8 位" /></label>
              </form>
            </div>
            <footer className="permission-modal-actions">
              <button type="button" className="button button-secondary" onClick={() => setOpen(false)} disabled={submitting}>取消</button>
              <button type="submit" form="customer-account-form" className="button button-primary" disabled={submitting}>{submitting ? <SpinnerGap className="is-spinning" size={18} /> : <UserPlus size={18} weight="bold" />} 创建账号</button>
            </footer>
          </section>
        </div>
      )}
    </section>
  );
}
