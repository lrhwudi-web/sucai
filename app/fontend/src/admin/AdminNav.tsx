import {
  ArrowsClockwise,
  ClockCounterClockwise,
  ChatCenteredText,
  ClipboardText,
  Database,
  Tray,
  PencilSimple,
  ShieldCheck,
} from "@phosphor-icons/react";
import type { AdminSection } from "./types";

interface AdminNavProps {
  active: AdminSection;
  pendingCount: number;
  messageCount: number;
  customerCount: number;
  customerOnly?: boolean;
  onChange: (section: AdminSection) => void;
}

const items = [
  { id: "pending" as const, label: "待确认素材", icon: Tray, count: "pending" },
  { id: "data" as const, label: "数据列表", icon: Database, count: "产品" },
  { id: "messages" as const, label: "客户留言", icon: ChatCenteredText, count: "messages" },
  { id: "permissions" as const, label: "客户账号与权限", icon: ShieldCheck, count: "customers" },
  { id: "edits" as const, label: "修改日志", icon: PencilSimple, count: "3" },
  { id: "history" as const, label: "入库记录", icon: ClockCounterClockwise, count: "3" },
  { id: "sync" as const, label: "同步与导入", icon: ArrowsClockwise, count: "正常" },
];

const customerItems = [
  { id: "permissions" as const, label: "客户账号与权限", icon: ShieldCheck, count: "customers" },
  { id: "orders" as const, label: "客户订单", icon: ClipboardText, count: "订单" },
];

export function AdminNav({ active, pendingCount, messageCount, customerCount, customerOnly = false, onChange }: AdminNavProps) {
  const visibleItems = customerOnly ? customerItems : items;
  return (
    <aside className="admin-nav-shell" aria-label="管理后台导航">
      <div className="admin-nav-title">
        <span>{customerOnly ? "Customer admin" : "Material admin"}</span>
        <strong>{customerOnly ? "客户管理" : "素材管理后台"}</strong>
        <small>{customerOnly ? "创建并维护自己的客户账号" : "Drive 与 NAS 入库控制台"}</small>
      </div>
      <nav className="admin-section-nav">
        {visibleItems.map(({ id, label, icon: Icon, count }) => (
          <button key={id} className={active === id ? "is-active" : ""} onClick={() => onChange(id)}>
            <Icon size={19} weight={active === id ? "fill" : "bold"} />
            <span>{label}</span>
            <em>{count === "pending" ? pendingCount : count === "messages" ? messageCount : count === "customers" ? customerCount : count}</em>
          </button>
        ))}
      </nav>
      <div className="admin-system-state">
        <span className="state-dot" />
        <div><strong>系统运行正常</strong><small>Drive 索引 · 已连接</small></div>
      </div>
    </aside>
  );
}
