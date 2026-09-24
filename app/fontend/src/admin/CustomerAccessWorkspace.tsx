import { useCallback, useEffect, useState } from "react";
import { SpinnerGap, WarningCircle } from "@phosphor-icons/react";
import { loadCustomerAccess } from "./adminService";
import { PermissionsPanel } from "./PermissionsPanel";
import type { CustomerAccessOverview } from "./types";

interface CustomerAccessWorkspaceProps {
  onNotify: (message: string) => void;
  isSuperAdmin: boolean;
  onCustomerCountChange?: (count: number) => void;
}

export function CustomerAccessWorkspace({ onNotify, isSuperAdmin, onCustomerCountChange }: CustomerAccessWorkspaceProps) {
  const [overview, setOverview] = useState<CustomerAccessOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setOverview(await loadCustomerAccess());
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "客户权限数据加载失败。";
      setError(message);
      onNotify(message);
    } finally {
      setLoading(false);
    }
  }, [onNotify]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (overview) onCustomerCountChange?.(overview.users.length);
  }, [onCustomerCountChange, overview]);

  if (loading && !overview) {
    return <div className="super-admin-loading" role="status"><SpinnerGap className="is-spinning" size={28} weight="bold" /><strong>正在加载客户权限</strong><span>正在读取角色隐藏规则与单客户放行范围。</span></div>;
  }

  if (error && !overview) {
    return <div className="super-admin-loading is-error"><WarningCircle size={30} weight="duotone" /><strong>客户权限加载失败</strong><span>{error}</span><button className="button button-primary" onClick={() => void refresh()}>重新加载</button></div>;
  }

  return overview ? (
    <PermissionsPanel
      users={overview.users}
      salespeople={overview.salespeople}
      isSuperAdmin={isSuperAdmin}
      rules={overview.rules}
      userGrants={overview.userGrants}
      permissionValues={overview.permissionValues}
      onRefresh={refresh}
      onNotify={onNotify}
    />
  ) : null;
}
