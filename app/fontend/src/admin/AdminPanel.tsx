import { useCallback, useEffect, useState } from "react";
import { SpinnerGap, WarningCircle } from "@phosphor-icons/react";
import { AdminNav } from "./AdminNav";
import { loadAdminOverview } from "./adminService";
import { PendingReview } from "./PendingReview";
import { EditLogPanel, UploadHistoryPanel } from "./RecordsPanels";
import { SyncPanel } from "./SyncPanel";
import { DataListPanel } from "./DataListPanel";
import { MessagesPanel } from "./MessagesPanel";
import { CustomerAccessWorkspace } from "./CustomerAccessWorkspace";
import { OrdersPanel } from "../orders/OrdersPanel";
import type { AuthUser } from "../services/auth";
import type { AdminOverview, AdminSection, ImportView } from "./types";

interface AdminPanelProps {
  user: AuthUser;
  search: string;
  onNotify: (message: string) => void;
  customerOnly?: boolean;
}

export function AdminPanel({ user, search, onNotify, customerOnly = false }: AdminPanelProps) {
  const [section, setSection] = useState<AdminSection>(() => {
    if (!customerOnly) return "pending";
    const requested = sessionStorage.getItem("kairay.admin.section");
    sessionStorage.removeItem("kairay.admin.section");
    return requested === "orders" ? "orders" : "permissions";
  });
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [pendingPage, setPendingPage] = useState(1);
  const [importView, setImportView] = useState<ImportView>("active");
  const [loading, setLoading] = useState(!customerOnly);
  const [error, setError] = useState("");
  const [customerCount, setCustomerCount] = useState(0);

  const refreshOverview = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const nextOverview = await loadAdminOverview(pendingPage, 6, importView);
      setOverview(nextOverview);
      if (nextOverview.importPage !== pendingPage) setPendingPage(nextOverview.importPage);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "管理后台数据加载失败。");
      throw caught;
    } finally {
      setLoading(false);
    }
  }, [importView, pendingPage]);

  useEffect(() => {
    if (customerOnly) return;
    refreshOverview().catch(() => undefined);
  }, [customerOnly, refreshOverview]);

  useEffect(() => {
    if (!customerOnly) return;
    const openSection = (event: Event) => {
      if ((event as CustomEvent<string>).detail === "orders") {
        sessionStorage.removeItem("kairay.admin.section");
        setSection("orders");
      }
    };
    window.addEventListener("kairay:open-admin-section", openSection);
    return () => window.removeEventListener("kairay:open-admin-section", openSection);
  }, [customerOnly]);

  const imports = overview?.imports || [];

  return (
    <div className="admin-shell">
      <AdminNav active={section} pendingCount={overview?.activeImportTotal || 0} messageCount={overview?.messageCount || 0} customerCount={overview?.users.length ?? customerCount} customerOnly={customerOnly} onChange={setSection} />
      <main className="admin-main">
        {customerOnly ? (
          section === "orders"
            ? <OrdersPanel user={user} onNotify={onNotify} embedded />
            : <CustomerAccessWorkspace onNotify={onNotify} isSuperAdmin={user.isSuperAdmin} onCustomerCountChange={setCustomerCount} />
        ) : loading && !overview ? (
          <div className="admin-loading" role="status"><SpinnerGap className="is-spinning" size={25} weight="bold" /><span>正在读取真实后台数据…</span></div>
        ) : error && !overview ? (
          <div className="admin-loading is-error"><WarningCircle size={28} weight="duotone" /><strong>后台数据加载失败</strong><span>{error}</span><button className="button button-primary" onClick={() => { setLoading(true); refreshOverview().catch(() => undefined); }}>重试</button></div>
        ) : overview ? (
          <>
            <div hidden={section !== "pending"}>
              <PendingReview imports={imports} total={overview.importTotal} batchTotal={overview.importBatchTotal} activeTotal={overview.activeImportTotal} disabledTotal={overview.disabledImportTotal} view={overview.importView} page={overview.importPage} pageSize={overview.importPageSize} pageCount={overview.importPages} statusCounts={overview.importStatusCounts} loading={loading} search={search} categoryOptions={overview.categoryOptions} themeOptions={overview.themeOptions} onViewChange={(nextView) => { setPendingPage(1); setImportView(nextView); }} onPageChange={setPendingPage} onChange={(next) => setOverview({ ...overview, imports: next })} onRefresh={refreshOverview} onNotify={onNotify} />
            </div>
            {section === "data" && <DataListPanel search={search} onNotify={onNotify} />}
            {section === "messages" && <MessagesPanel search={search} />}
            {section === "permissions" && <CustomerAccessWorkspace onNotify={onNotify} isSuperAdmin={user.isSuperAdmin} onCustomerCountChange={setCustomerCount} />}
            {section === "edits" && <EditLogPanel logs={overview.editLogs} />}
            {section === "history" && <UploadHistoryPanel records={overview.uploadHistory} />}
            {section === "sync" && <SyncPanel status={overview.syncStatus} onRefresh={refreshOverview} onNotify={onNotify} />}
          </>
        ) : null}
      </main>
    </div>
  );
}
