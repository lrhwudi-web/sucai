import { useEffect, useRef, useState } from "react";
import {
  BellSimple,
  CaretDown,
  ClipboardText,
  Gauge,
  ListMagnifyingGlass,
  SignOut,
  SlidersHorizontal,
  ShieldStar,
  SpinnerGap,
  Table,
} from "@phosphor-icons/react";
import { BrandMark } from "./BrandMark";
import type { AuthUser } from "../services/auth";

interface HeaderProps {
  activeView: "catalogue" | "quotation" | "orders" | "admin" | "super-admin";
  onNavigate: (view: "landing" | "catalogue" | "quotation" | "orders" | "admin" | "super-admin") => void;
  onToggleFilters: () => void;
  onNotify: (message: string) => void;
  pendingNotificationCount: number;
  onLogout: () => void;
  loggingOut: boolean;
  user: AuthUser;
}

export function Header({
  activeView,
  onNavigate,
  onToggleFilters,
  onNotify,
  pendingNotificationCount,
  onLogout,
  loggingOut,
  user,
}: HeaderProps) {
  const isAdminSurface = activeView === "admin" || activeView === "super-admin" || (activeView === "orders" && user.isAdmin);
  const canAdmin = user.isAdmin;
  const canSuperAdmin = user.isSuperAdmin;
  const accountName = user.name || user.email;
  const accountInitial = accountName.slice(0, 1).toUpperCase();
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const accountMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!accountMenuOpen) return;

    const closeOnOutsidePress = (event: PointerEvent) => {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAccountMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [accountMenuOpen]);

  const openNotifications = () => {
    if (canAdmin && pendingNotificationCount > 0) {
      sessionStorage.setItem("kairay.admin.section", "orders");
      onNavigate("admin");
      window.setTimeout(() => window.dispatchEvent(new CustomEvent("kairay:open-admin-section", { detail: "orders" })), 0);
      onNotify(`还有 ${pendingNotificationCount} 个订单未确认`);
      return;
    }
    onNotify(isAdminSurface ? "当前没有未确认订单" : "You are all caught up—no new order notifications.");
  };

  return (
    <header className={`topbar ${isAdminSurface ? "is-admin" : ""}`}>
      <button className="wordmark wordmark-button" type="button" onClick={() => onNavigate("landing")} aria-label={isAdminSurface ? "返回 Kairay Golf 客户首页" : "Return to the Kairay Golf client homepage"}>
        <BrandMark className="wordmark-brand" subtitle={isAdminSurface ? "Material Index" : "Client Asset Center"} />
      </button>

      <nav className="primary-nav" aria-label={isAdminSurface ? "主导航" : "Primary navigation"}>
        <button className={activeView === "catalogue" ? "nav-item is-active" : "nav-item"} onClick={() => onNavigate("catalogue")} aria-current={activeView === "catalogue" ? "page" : undefined}>
          <ListMagnifyingGlass size={18} weight="bold" />
          {isAdminSurface ? "素材库" : "Asset Library"}
        </button>
        <button className={activeView === "quotation" ? "nav-item is-active" : "nav-item"} onClick={() => onNavigate("quotation")} aria-current={activeView === "quotation" ? "page" : undefined}>
          <Table size={18} weight="bold" />
          {isAdminSurface ? "产品报价表" : "Product Catalog"}
        </button>
        {!user.isAdmin && (
          <button className={activeView === "orders" ? "nav-item is-active" : "nav-item"} onClick={() => onNavigate("orders")} aria-current={activeView === "orders" ? "page" : undefined}>
            <ClipboardText size={18} weight="bold" />
            My Orders
          </button>
        )}
        {canAdmin && (
          <button className={activeView === "admin" ? "nav-item is-active" : "nav-item"} onClick={() => onNavigate("admin")} aria-current={activeView === "admin" ? "page" : undefined}>
            <Gauge size={18} weight="bold" />
            {isAdminSurface ? "管理后台" : "Admin"}
          </button>
        )}
        {canSuperAdmin && (
          <button className={activeView === "super-admin" ? "nav-item is-active" : "nav-item"} onClick={() => onNavigate("super-admin")} aria-current={activeView === "super-admin" ? "page" : undefined}>
            <ShieldStar size={18} weight="bold" />
            {isAdminSurface ? "超级管理" : "Super admin"}
          </button>
        )}
      </nav>

      <div className="account-actions" ref={accountMenuRef}>
        {canAdmin && (
          <button className="icon-button compact-admin-trigger" onClick={() => onNavigate(isAdminSurface ? "catalogue" : "admin")} aria-label={isAdminSurface ? "返回素材库" : "Open admin"}>
            {isAdminSurface ? <ListMagnifyingGlass size={20} weight="bold" /> : <Gauge size={20} weight="bold" />}
          </button>
        )}
        <button className={activeView === "catalogue" ? "icon-button mobile-filter-trigger" : "icon-button mobile-filter-trigger is-hidden"} onClick={onToggleFilters} aria-label={isAdminSurface ? "打开筛选" : "Open filters"}>
          <SlidersHorizontal size={20} weight="bold" />
        </button>
        <button
          className="icon-button notification-button"
          onClick={openNotifications}
          aria-label={canAdmin && pendingNotificationCount > 0 ? `还有 ${pendingNotificationCount} 个订单未确认` : (isAdminSurface ? "当前没有未确认订单" : "View notifications")}
        >
          <BellSimple size={20} weight="bold" />
          {canAdmin && pendingNotificationCount > 0 && (
            <span className="notification-badge" aria-hidden="true">
              {pendingNotificationCount > 99 ? "99+" : pendingNotificationCount}
            </span>
          )}
        </button>
        <button
          className="account-chip"
          type="button"
          onClick={() => setAccountMenuOpen((current) => !current)}
          aria-haspopup="menu"
          aria-expanded={accountMenuOpen}
          aria-controls="account-menu"
          aria-label={isAdminSurface ? "打开账户菜单" : "Open account menu"}
        >
          <span className="account-avatar">{accountInitial}</span>
          <span className="account-chip-copy">
            <strong>{accountName}</strong>
            <small>{canSuperAdmin ? (isAdminSurface ? "超级管理员" : "Super administrator") : canAdmin ? (isAdminSurface ? "管理员" : "Administrator") : "Client Portal"}</small>
          </span>
          <CaretDown className="account-chip-caret" size={14} weight="bold" />
        </button>
        {accountMenuOpen && (
          <div className="account-menu" id="account-menu" role="menu">
            <div className="account-menu-summary">
              <span className="account-avatar">{accountInitial}</span>
              <span>
                <strong>{accountName}</strong>
                <small>{user.email}</small>
              </span>
            </div>
            {canAdmin && (
              <button
                className="account-menu-item"
                type="button"
                role="menuitem"
                onClick={() => { setAccountMenuOpen(false); onNavigate("admin"); }}
              >
                <Gauge size={18} weight="bold" />
                <span>管理后台</span>
              </button>
            )}
            {canSuperAdmin && (
              <button
                className="account-menu-item"
                type="button"
                role="menuitem"
                onClick={() => { setAccountMenuOpen(false); onNavigate("super-admin"); }}
              >
                <ShieldStar size={18} weight="bold" />
                <span>超级管理</span>
              </button>
            )}
            <button
              className="account-menu-item account-menu-signout"
              type="button"
              role="menuitem"
              disabled={loggingOut}
              onClick={onLogout}
            >
              {loggingOut ? <SpinnerGap className="is-spinning" size={18} weight="bold" /> : <SignOut size={18} weight="bold" />}
              <span>{loggingOut ? "Signing out…" : "Sign out"}</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
