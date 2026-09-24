import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  Copy,
  Eye,
  EyeSlash,
  Funnel,
  Key,
  LockKey,
  MagnifyingGlass,
  PencilSimple,
  Power,
  ShieldCheck,
  SpinnerGap,
  UserPlus,
  UsersThree,
  X,
} from "@phosphor-icons/react";
import { normalizeBrandLabel } from "../utils/category";
import { apiEnabled } from "../services/auth";
import { postAdminAction } from "./adminService";
import type { AdminUser, PermissionRule, SalespersonOption, UserPermissionGrant } from "./types";

type PermissionModal = "account" | "edit" | null;
type RuleScope = "brand" | "category" | "asset_type" | "other" | "sku";
type PermissionPreset = "all" | "brands" | "custom";
type PermissionMode = AdminUser["permissionMode"];
type WizardStep = 1 | 2 | 3;

interface PermissionsPanelProps {
  users: AdminUser[];
  salespeople: SalespersonOption[];
  isSuperAdmin: boolean;
  rules: PermissionRule[];
  userGrants: UserPermissionGrant[];
  permissionValues: Record<string, string[]>;
  onRefresh: () => Promise<void>;
  onNotify: (message: string) => void;
}

interface AccountDraft {
  email: string;
  name: string;
  role: "overseas_customer" | "domestic_customer" | "service_provider";
  password: string;
}

interface AccountEditDraft {
  name: string;
  role: AccountDraft["role"];
  disabled: boolean;
}

interface PermissionOverflowProps {
  label: string;
  values: string[];
  onShow: (target: HTMLElement, label: string, values: string[]) => void;
  onHide: () => void;
}

function PermissionOverflow({ label, values, onShow, onHide }: PermissionOverflowProps) {
  if (!values.length) return null;
  return (
    <button
      type="button"
      className="permission-chip is-more"
      aria-label={`查看剩余${label}：${values.join("、")}`}
      onMouseEnter={(event) => onShow(event.currentTarget, label, values)}
      onMouseLeave={onHide}
      onFocus={(event) => onShow(event.currentTarget, label, values)}
      onBlur={onHide}
    >
      +{values.length}
    </button>
  );
}

const defaultAccountDraft: AccountDraft = { email: "", name: "", role: "overseas_customer", password: "" };
const defaultAccountEditDraft: AccountEditDraft = { name: "", role: "overseas_customer", disabled: false };

function catalogFollowUp(user: AdminUser) {
  const activity = user.catalogEngagement;
  if (!activity) return { label: "新目录：暂无记录", kind: "none" };
  if (activity.orderCount) return { label: `已下单 ${activity.orderCount} 次${activity.lastOrderAt ? ` · ${activity.lastOrderAt}` : ""}`, kind: "ordered" };
  if (activity.productAdds) return { label: `曾选品，尚未下单${activity.lastProductAddAt ? ` · ${activity.lastProductAddAt}` : ""}`, kind: "interest" };
  if (activity.catalogViews) return { label: `已查看目录 ${activity.catalogViews} 次${activity.lastCatalogViewAt ? ` · ${activity.lastCatalogViewAt}` : ""}`, kind: "viewed" };
  if (activity.inviteOpens) return { label: `已打开邀请，尚未看目录${activity.lastInviteOpenAt ? ` · ${activity.lastInviteOpenAt}` : ""}`, kind: "viewed" };
  if (activity.shareCopies) return { label: `已复制邀请，未见查看${activity.lastShareCopyAt ? ` · ${activity.lastShareCopyAt}` : ""}`, kind: "shared" };
  return { label: "新目录：暂无记录", kind: "none" };
}

const roleLabels: Record<string, string> = {
  internal_staff: "内部员工",
  overseas_customer: "海外客户",
  domestic_customer: "国内客户",
  service_provider: "服务商",
  admin: "管理员",
  super_admin: "超级管理员",
};

const roleValues: Record<string, AccountDraft["role"]> = {
  overseas_customer: "overseas_customer",
  domestic_customer: "domestic_customer",
  service_provider: "service_provider",
  海外客户: "overseas_customer",
  国内客户: "domestic_customer",
  服务商: "service_provider",
};

const scopeLabels: Record<RuleScope, string> = {
  brand: "品牌",
  category: "产品分类",
  asset_type: "素材类型",
  other: "其他标签",
  sku: "SKU",
};

const scopeAliases: Record<RuleScope, string[]> = {
  brand: ["brand", "品牌"],
  category: ["category", "产品分类", "分类"],
  asset_type: ["asset_type", "素材类型"],
  other: ["other", "其他标签"],
  sku: ["sku", "SKU"],
};

function normalizeScope(scope: string): string {
  return scope.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function isScope(scope: string, expected: RuleScope): boolean {
  const normalized = normalizeScope(scope);
  return scopeAliases[expected].some((alias) => normalizeScope(alias) === normalized);
}

function createPassword(): string {
  const groups = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%"];
  const randomIndex = (length: number) => {
    const values = new Uint32Array(1);
    window.crypto.getRandomValues(values);
    return values[0] % length;
  };
  const result = groups.map((group) => group[randomIndex(group.length)]);
  const pool = groups.join("");
  while (result.length < 12) result.push(pool[randomIndex(pool.length)]);
  return result.sort(() => Math.random() - 0.5).join("");
}

function initials(name: string): string {
  const value = name.trim();
  if (!value) return "客";
  const words = value.split(/\s+/).filter(Boolean);
  if (words.length > 1) return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  return value.slice(0, 1).toUpperCase();
}

export function PermissionsPanel({
  users: providedUsers,
  salespeople,
  isSuperAdmin,
  userGrants: providedUserGrants,
  permissionValues,
  onRefresh,
  onNotify,
}: PermissionsPanelProps) {
  const [users, setUsers] = useState(providedUsers);
  const [userGrants, setUserGrants] = useState(providedUserGrants);
  const [openModal, setOpenModal] = useState<PermissionModal>(null);
  const [submitting, setSubmitting] = useState(false);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [permissionFilter, setPermissionFilter] = useState<"all" | PermissionMode>("all");
  const [salespersonFilter, setSalespersonFilter] = useState("all");
  const [wizardStep, setWizardStep] = useState<WizardStep>(1);
  const [accountDraft, setAccountDraft] = useState<AccountDraft>(defaultAccountDraft);
  const [permissionPreset, setPermissionPreset] = useState<PermissionPreset>("all");
  const [selectedBrands, setSelectedBrands] = useState<string[]>([]);
  const [selectedOther, setSelectedOther] = useState<string[]>([]);
  const [modalError, setModalError] = useState("");
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [accountEditDraft, setAccountEditDraft] = useState<AccountEditDraft>(defaultAccountEditDraft);
  const [editPermissionPreset, setEditPermissionPreset] = useState<PermissionPreset>("all");
  const [editSelectedBrands, setEditSelectedBrands] = useState<string[]>([]);
  const [editSelectedOther, setEditSelectedOther] = useState<string[]>([]);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [showTemporaryPassword, setShowTemporaryPassword] = useState(false);
  const [passwordCopied, setPasswordCopied] = useState(false);
  const [renewingId, setRenewingId] = useState<number | null>(null);
  const [permissionTooltip, setPermissionTooltip] = useState<null | { label: string; values: string[]; left: number; top: number }>(null);

  useEffect(() => setUsers(providedUsers), [providedUsers]);
  useEffect(() => setUserGrants(providedUserGrants), [providedUserGrants]);

  useEffect(() => {
    if (!openModal) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) setOpenModal(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openModal, submitting]);

  const brandOptions = useMemo(() => permissionValues.brand?.filter(Boolean) || [], [permissionValues]);
  const otherOptions = useMemo(() => permissionValues.other?.filter(Boolean) || [], [permissionValues]);
  const roleOptions = useMemo(() => Array.from(new Set(users.map((user) => user.role))), [users]);
  const hasUnassignedCustomers = useMemo(() => users.some((user) => !user.createdByUserId), [users]);

  const grantsByUser = useMemo(() => {
    const grouped = new Map<number, UserPermissionGrant[]>();
    userGrants.forEach((grant) => grouped.set(grant.userId, [...(grouped.get(grant.userId) || []), grant]));
    return grouped;
  }, [userGrants]);

  const visibleBrandsFor = (user: AdminUser): string[] => {
    const grants = grantsByUser.get(user.id) || [];
    const grantedBrands = grants.filter((grant) => isScope(grant.scope, "brand")).map((grant) => grant.value);
    if (user.permissionMode === "allowlist") return brandOptions.filter((brand) => grantedBrands.includes(brand));
    return brandOptions;
  };

  const extraScopesFor = (user: AdminUser): string[] => {
    return visibleOtherFor(user);
  };

  const visibleOtherFor = (user: AdminUser): string[] => {
    const grants = grantsByUser.get(user.id) || [];
    const grantedOther = grants.filter((grant) => isScope(grant.scope, "other")).map((grant) => grant.value);
    if (user.permissionMode === "allowlist") {
      return otherOptions.filter((value) => value !== "No Brand" && grantedOther.includes(value));
    }
    return otherOptions.filter((value) => value !== "No Brand");
  };

  const wizardSelectedOther = selectedOther;
  const editorSelectedOther = editSelectedOther;

  const filteredUsers = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return users.filter((user) => {
      const matchesQuery = !normalizedQuery || `${user.name} ${user.email}`.toLowerCase().includes(normalizedQuery);
      const matchesRole = roleFilter === "all" || user.role === roleFilter;
      const matchesPermission = permissionFilter === "all" || user.permissionMode === permissionFilter;
      const matchesSalesperson = salespersonFilter === "all"
        || (salespersonFilter === "unassigned" ? !user.createdByUserId : String(user.createdByUserId) === salespersonFilter);
      return matchesQuery && matchesRole && matchesPermission && matchesSalesperson;
    });
  }, [permissionFilter, query, roleFilter, salespersonFilter, users]);

  const closeModal = () => {
    if (!submitting) {
      setOpenModal(null);
      setModalError("");
      setTemporaryPassword("");
    }
  };

  const openAccountWizard = () => {
    setWizardStep(1);
    setAccountDraft(defaultAccountDraft);
    setPermissionPreset("all");
    setSelectedBrands([]);
    setSelectedOther([]);
    setModalError("");
    setOpenModal("account");
  };

  const reportModalError = (message: string) => {
    setModalError(message);
    onNotify(message);
  };

  const permissionEntries = (preset: PermissionPreset, brands: string[], other: string[]) => preset === "all"
    ? [
        ...brandOptions.map((value) => ({ scope: "brand", value })),
        ...otherOptions.filter((value) => value !== "No Brand").map((value) => ({ scope: "other", value })),
      ]
    : [
        ...brands.map((value) => ({ scope: "brand", value })),
        ...(preset === "custom" ? other.map((value) => ({ scope: "other", value })) : []),
      ];

  const showPermissionTooltip = (target: HTMLElement, label: string, values: string[]) => {
    const rect = target.getBoundingClientRect();
    const width = 280;
    setPermissionTooltip({
      label,
      values,
      left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      top: Math.min(rect.bottom + 8, window.innerHeight - 170),
    });
  };

  const openAccountEditor = (user: AdminUser) => {
    const grants = grantsByUser.get(user.id) || [];
    const explicitOther = grants.filter((grant) => isScope(grant.scope, "other")).map((grant) => grant.value);
    const effectiveBrands = visibleBrandsFor(user);
    const effectiveOther = visibleOtherFor(user);
    const hasAllPermissions = effectiveBrands.length === brandOptions.length
      && effectiveOther.length === otherOptions.filter((value) => value !== "No Brand").length;
    setEditingUser(user);
    setAccountEditDraft({ name: user.name, role: roleValues[user.role] || "overseas_customer", disabled: user.disabled });
    setEditPermissionPreset(hasAllPermissions ? "all" : explicitOther.length ? "custom" : "brands");
    setEditSelectedBrands(effectiveBrands);
    setEditSelectedOther(effectiveOther);
    setTemporaryPassword("");
    setShowTemporaryPassword(false);
    setPasswordCopied(false);
    setModalError("");
    setOpenModal("edit");
  };

  const switchEditPermissionPreset = (preset: PermissionPreset) => {
    setEditPermissionPreset(preset);
    setModalError("");
  };

  const toggleValue = (value: string, selected: string[], setSelected: (values: string[]) => void) => {
    setSelected(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);
  };

  const validateWizardStep = (): boolean => {
    if (wizardStep === 1 && (!accountDraft.name.trim() || !/^\S+@\S+\.\S+$/.test(accountDraft.email) || accountDraft.password.length < 8)) {
      reportModalError("请填写客户姓名、有效业务邮箱和至少 8 位初始密码。");
      return false;
    }
    if (wizardStep === 2 && permissionPreset !== "all") {
      const hasSelection = selectedBrands.length > 0 || (permissionPreset === "custom" && selectedOther.length > 0);
      if (!hasSelection) {
        reportModalError("请至少选择一个可见品牌或扩展素材范围。");
        return false;
      }
    }
    setModalError("");
    return true;
  };

  const nextWizardStep = () => {
    if (!validateWizardStep()) return;
    setWizardStep((current) => Math.min(3, current + 1) as WizardStep);
  };

  const createAccount = async () => {
    if (!validateWizardStep()) return;
    const permissionMode: PermissionMode = "allowlist";
    const newPermissionEntries = permissionEntries(permissionPreset, selectedBrands, wizardSelectedOther);
    setSubmitting(true);
    try {
      const result = await postAdminAction("/api/admin/users", {
        email: accountDraft.email,
        name: accountDraft.name,
        role: accountDraft.role,
        password: accountDraft.password,
        permission_mode: permissionMode,
        permission_scopes: newPermissionEntries.map((entry) => entry.scope),
        permission_values: newPermissionEntries.map((entry) => entry.value),
      });
      if (result.mode === "api") {
        setSalespersonFilter("all");
        await onRefresh();
      } else {
        const userId = Date.now();
        const role = roleLabels[accountDraft.role];
        setUsers((current) => [{ id: userId, email: accountDraft.email, name: accountDraft.name, role, permissionMode, disabled: false, createdAt: "今天" }, ...current]);
        setUserGrants((current) => [
          ...newPermissionEntries.map((entry, index) => ({
            id: userId + index + 1,
            userId,
            userName: accountDraft.name,
            userEmail: accountDraft.email,
            scope: scopeLabels[entry.scope as RuleScope],
            value: entry.value,
            createdAt: "今天",
          })),
          ...current,
        ]);
      }
      setOpenModal(null);
      onNotify("客户账号与权限已同时创建");
    } catch (error) {
      reportModalError(error instanceof Error ? error.message : "客户账号创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const saveEditedAccount = async () => {
    if (!editingUser) return;
    if (!accountEditDraft.name.trim()) {
      reportModalError("客户姓名不能为空。");
      return;
    }
    const newPermissionEntries = permissionEntries(editPermissionPreset, editSelectedBrands, editorSelectedOther);
    if (!newPermissionEntries.length) {
      reportModalError("请至少为账号选择一个品牌或扩展素材权限。");
      return;
    }
    const permissionMode: PermissionMode = "allowlist";
    setSubmitting(true);
    setModalError("");
    try {
      const result = await postAdminAction(`/api/admin/users/${editingUser.id}`, {
        name: accountEditDraft.name,
        role: accountEditDraft.role,
        disabled: accountEditDraft.disabled,
        permission_mode: permissionMode,
        permission_scopes: newPermissionEntries.map((entry) => entry.scope),
        permission_values: newPermissionEntries.map((entry) => entry.value),
      });
      if (result.mode === "api") {
        await onRefresh();
      } else {
        const displayRole = roleLabels[accountEditDraft.role];
        setUsers((current) => current.map((user) => user.id === editingUser.id ? {
          ...user,
          name: accountEditDraft.name,
          role: displayRole,
          disabled: accountEditDraft.disabled,
          permissionMode,
        } : user));
        setUserGrants((current) => [
          ...newPermissionEntries.map((entry, index) => ({
            id: Date.now() + index,
            userId: editingUser.id,
            userName: accountEditDraft.name,
            userEmail: editingUser.email,
            scope: scopeLabels[entry.scope as RuleScope],
            value: entry.value,
            createdAt: "今天",
          })),
          ...current.filter((grant) => grant.userId !== editingUser.id),
        ]);
      }
      setOpenModal(null);
      setTemporaryPassword("");
      onNotify(accountEditDraft.disabled ? "账号已停用，权限修改已保存" : "账号资料与权限已更新");
    } catch (error) {
      reportModalError(error instanceof Error ? error.message : "账号修改保存失败");
    } finally {
      setSubmitting(false);
    }
  };

  const resetEditedPassword = async () => {
    if (!editingUser) return;
    setSubmitting(true);
    setModalError("");
    try {
      const result = await postAdminAction(`/api/admin/users/${editingUser.id}/reset-password`);
      const payload = result.mode === "api" ? result.data as { temporary_password?: string } | undefined : undefined;
      const password = payload?.temporary_password || createPassword();
      setTemporaryPassword(password);
      setShowTemporaryPassword(true);
      setPasswordCopied(false);
    } catch (error) {
      reportModalError(error instanceof Error ? error.message : "临时密码重置失败");
    } finally {
      setSubmitting(false);
    }
  };

  const copyTemporaryPassword = async () => {
    if (!temporaryPassword) return;
    try {
      await navigator.clipboard.writeText(temporaryPassword);
      setPasswordCopied(true);
    } catch {
      reportModalError("复制失败，请手动选择临时密码。");
    }
  };

  const copyCustomerCatalogInvite = async (user: AdminUser) => {
    if (user.disabled || user.expired) return;
    const token = apiEnabled() ? crypto.randomUUID().replaceAll("-", "") : "";
    const catalogUrl = new URL(window.location.pathname, window.location.origin);
    if (token) catalogUrl.searchParams.set("invite", token);
    catalogUrl.hash = "quotation";
    const message = user.role === "海外客户" || user.role === "overseas_customer"
      ? `Hi ${user.name}, here is your Kairay Golf product catalog: ${catalogUrl}\nSign in to view products, enter quantities, and send your order. Reply here if you need a quote or help.`
      : `${user.name}，这是您的凯瑞高尔夫产品目录：${catalogUrl}\n登录后可查看产品、填写数量并提交订单。如需报价或协助，直接在微信回复我。`;
    try {
      await navigator.clipboard.writeText(message);
    } catch {
      onNotify("复制失败，请检查浏览器剪贴板权限后重试");
      return;
    }
    try {
      if (token) await postAdminAction(`/api/admin/users/${user.id}/catalog-invite`, { token });
    } catch {
      onNotify("链接未启用，请勿发送刚复制的邀请；请重试");
      return;
    }
    try {
      const result = await postAdminAction(`/api/admin/users/${user.id}/catalog-share-copy`);
      if (result.mode === "api") await onRefresh();
      else setUsers(current => current.map(item => item.id === user.id ? {
        ...item,
        catalogEngagement: {
          shareCopies: (item.catalogEngagement?.shareCopies || 0) + 1,
          lastShareCopyAt: "刚刚",
          inviteOpens: item.catalogEngagement?.inviteOpens || 0,
          lastInviteOpenAt: item.catalogEngagement?.lastInviteOpenAt || "",
          catalogViews: item.catalogEngagement?.catalogViews || 0,
          lastCatalogViewAt: item.catalogEngagement?.lastCatalogViewAt || "",
          productAdds: item.catalogEngagement?.productAdds || 0,
          lastProductAddAt: item.catalogEngagement?.lastProductAddAt || "",
          orderCount: item.catalogEngagement?.orderCount || 0,
          lastOrderAt: item.catalogEngagement?.lastOrderAt || "",
        },
      } : item));
      onNotify(`已复制 ${user.name} 的目录邀请，可粘贴到微信`);
    } catch {
      onNotify("邀请链接已启用，可粘贴到微信；复制记录暂未保存");
    }
  };

  const renewCustomerAccount = async (user: AdminUser) => {
    if (!user.expired || renewingId !== null) return;
    setRenewingId(user.id);
    try {
      const result = await postAdminAction(`/api/admin/users/${user.id}/renew`);
      if (result.mode === "api") await onRefresh();
      else setUsers(current => current.map(item => item.id === user.id ? { ...item, disabled: false, expired: false, expiresAt: "15 天后" } : item));
      onNotify(`${user.name} 的账号已续期 15 天，原有权限保持不变`);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "续期失败，请稍后重试");
    } finally {
      setRenewingId(null);
    }
  };

  return (
    <section className="admin-section customer-access-page">
      <header className="customer-access-heading">
        <div><span className="eyebrow">Customer accounts & access</span><h1>客户账号与权限</h1><p>创建客户账号时直接设定可见范围，并在一个工作台持续维护。</p></div>
        <button className="button button-primary customer-access-create" onClick={openAccountWizard}><UserPlus size={18} weight="bold" /> 创建客户账号</button>
      </header>

      <div className="customer-access-shell">
        <div className="customer-access-toolbar">
              <label className="customer-access-search"><MagnifyingGlass size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索姓名或邮箱" /></label>
              <div className="customer-access-filters"><Funnel size={17} />{isSuperAdmin && <select value={salespersonFilter} onChange={(event) => setSalespersonFilter(event.target.value)} aria-label="筛选业务员"><option value="all">全部业务员</option>{salespeople.map((salesperson) => <option value={String(salesperson.id)} key={salesperson.id}>{salesperson.name}{salesperson.disabled ? "（已停用）" : ""}</option>)}{hasUnassignedCustomers && <option value="unassigned">未分配业务员</option>}</select>}<select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)} aria-label="筛选角色"><option value="all">全部角色</option>{roleOptions.map((role) => <option value={role} key={role}>{role}</option>)}</select><select value={permissionFilter} onChange={(event) => setPermissionFilter(event.target.value as typeof permissionFilter)} aria-label="筛选权限方式"><option value="all">全部权限方式</option><option value="allowlist">单账号权限</option></select></div>
        </div>

        <div className="customer-access-table" role="table" aria-label="客户账号列表">
              <div className="customer-access-row is-head" role="row"><span>账号</span><span>角色</span><span>可见品牌</span><span>扩展素材</span><span>有效期至</span><span>状态</span><span>操作</span></div>
              {filteredUsers.map((user) => {
                const visibleBrands = visibleBrandsFor(user);
                const extras = extraScopesFor(user);
                const allBrands = visibleBrands.length === brandOptions.length && brandOptions.length > 0;
                return (
                  <div className="customer-access-row" role="row" key={user.id}>
                    <span className="customer-account-cell"><i>{initials(user.name)}</i><span><strong>{user.name}</strong><small>{user.email}</small><em className={`customer-follow-up is-${catalogFollowUp(user).kind}`} title={`复制邀请 ${user.catalogEngagement?.shareCopies || 0} 次；邀请打开 ${user.catalogEngagement?.inviteOpens || 0} 次；目录查看 ${user.catalogEngagement?.catalogViews || 0} 次；加单 ${user.catalogEngagement?.productAdds || 0} 次；正式订单 ${user.catalogEngagement?.orderCount || 0} 次`}>{catalogFollowUp(user).label}</em></span></span>
                    <span><mark className="customer-role-badge">{user.role}</mark></span>
                    <span className="permission-chip-list">{allBrands ? <em className="permission-chip is-all">全部品牌</em> : visibleBrands.slice(0, 2).map((brand) => <em className="permission-chip" key={brand}>{normalizeBrandLabel(brand)}</em>)}{!allBrands && <PermissionOverflow label="品牌" values={visibleBrands.slice(2).map(normalizeBrandLabel)} onShow={showPermissionTooltip} onHide={() => setPermissionTooltip(null)} />}{!visibleBrands.length && <small className="permission-empty">未开放品牌</small>}</span>
                    <span className="permission-chip-list">{extras.slice(0, 1).map((value) => <em className="permission-chip is-muted" key={value}>{value}</em>)}<PermissionOverflow label="扩展素材" values={extras.slice(1)} onShow={showPermissionTooltip} onHide={() => setPermissionTooltip(null)} />{!extras.length && <small className="permission-empty">—</small>}</span>
                    <span className="customer-access-date">{user.expiresAt || "创建后 15 天"}</span>
                    <span><em className={`customer-status ${user.disabled ? "is-disabled" : ""}`}><i /> {user.expired ? "已过期" : user.disabled ? "已停用" : "正常"}</em></span>
                    <span className="customer-access-actions">{user.expired && <button className="table-icon renew-catalog-action" type="button" disabled={renewingId !== null} onClick={() => void renewCustomerAccount(user)} aria-label={`为 ${user.name} 续期 15 天`} title="保留现有权限，为过期账号续期 15 天">{renewingId === user.id ? "续期中" : "续期"}</button>}<button className="table-icon share-catalog-action" type="button" disabled={user.disabled || user.expired} onClick={() => void copyCustomerCatalogInvite(user)} aria-label={`复制发给 ${user.name} 的目录消息`} title={user.disabled || user.expired ? "账号不可用，启用或续期后才能邀请" : "复制目录链接和说明，粘贴到微信"}>发目录</button><button className="table-icon" type="button" onClick={() => openAccountEditor(user)} aria-label={`修改 ${user.name} 的账号`} title="修改账号、权限和密码"><PencilSimple size={17} weight="bold" /></button></span>
                  </div>
                );
              })}
              {!filteredUsers.length && <div className="customer-access-empty">没有符合筛选条件的客户账号</div>}
        </div>
        <footer className="customer-access-table-footer">共 {filteredUsers.length} 个账号 · 所有可见范围均按账号单独保存</footer>
      </div>

      {permissionTooltip && (
        <div className="permission-overflow-tooltip" role="tooltip" style={{ left: permissionTooltip.left, top: permissionTooltip.top }}>
          <strong>剩余{permissionTooltip.label}</strong>
          <ul>{permissionTooltip.values.map((value) => <li key={value}>{value}</li>)}</ul>
        </div>
      )}

      {openModal && (
        <div className="review-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeModal(); }}>
          {openModal === "account" ? (
            <section className="account-wizard" role="dialog" aria-modal="true" aria-labelledby="account-wizard-title">
              <header className="account-wizard-heading"><div><span>Customer account setup</span><h2 id="account-wizard-title">创建客户账号</h2><small>账号资料和权限一次完成，创建后立即生效。</small></div><button type="button" onClick={closeModal} disabled={submitting} aria-label="关闭弹窗"><X size={20} weight="bold" /></button></header>
              <div className="account-wizard-steps" aria-label="创建步骤">
                {[{ step: 1, title: "填写账号", hint: "客户资料与登录信息" }, { step: 2, title: "选择权限", hint: "品牌与扩展素材" }, { step: 3, title: "确认创建", hint: "检查后立即生效" }].map((item) => <div className={`${wizardStep === item.step ? "is-active" : ""} ${wizardStep > item.step ? "is-complete" : ""}`} key={item.step}><i>{wizardStep > item.step ? <Check size={16} weight="bold" /> : item.step}</i><span><strong>{item.title}</strong><small>{item.hint}</small></span></div>)}
              </div>
              <div className="account-wizard-body">
                {modalError && <div className="permission-error-banner" role="alert"><strong>无法继续</strong><span>{modalError}</span></div>}
                {wizardStep === 1 && <div className="account-wizard-form"><div className="account-wizard-intro"><span>第一步</span><h3>填写客户账号资料</h3><p>管理员和超级管理员不在这里创建，仍由钉钉组织架构管理。</p></div><div className="account-form-grid"><label>客户姓名<input value={accountDraft.name} onChange={(event) => setAccountDraft({ ...accountDraft, name: event.target.value })} placeholder="例如 Johan" autoFocus /></label><label>业务邮箱<input type="email" value={accountDraft.email} onChange={(event) => setAccountDraft({ ...accountDraft, email: event.target.value })} placeholder="name@company.com" /></label><label>客户角色<select value={accountDraft.role} onChange={(event) => setAccountDraft({ ...accountDraft, role: event.target.value as AccountDraft["role"] })}><option value="overseas_customer">海外客户</option><option value="domestic_customer">国内客户</option><option value="service_provider">服务商</option></select></label><label>初始密码<span className="account-password-field"><input type="text" value={accountDraft.password} onChange={(event) => setAccountDraft({ ...accountDraft, password: event.target.value })} placeholder="至少 8 位" /><button type="button" onClick={() => setAccountDraft({ ...accountDraft, password: createPassword() })}>随机生成</button></span></label></div></div>}

                {wizardStep === 2 && <div className="account-permission-step"><aside className="account-summary-card"><span>账号摘要</span><i>{initials(accountDraft.name)}</i><h3>{accountDraft.name}</h3><p>{accountDraft.email}</p><dl><div><dt>客户角色</dt><dd>{roleLabels[accountDraft.role]}</dd></div><div><dt>权限方式</dt><dd>{permissionPreset === "all" ? "全部素材" : "单账号指定"}</dd></div></dl></aside><div className="account-permission-picker"><div className="account-wizard-intro"><span>第二步</span><h3>选择账号可见权限</h3><p>每个账号的品牌和扩展素材权限都独立保存。</p></div><div className="permission-preset-list"><label className={permissionPreset === "all" ? "is-selected" : ""}><input type="radio" name="permission-preset" checked={permissionPreset === "all"} onChange={() => setPermissionPreset("all")} /><i><ShieldCheck size={19} weight="duotone" /></i><span><strong>开放全部素材</strong><small>把当前全部品牌和扩展素材明确授权给这个账号。</small></span><CheckCircle size={20} weight={permissionPreset === "all" ? "fill" : "regular"} /></label><label className={permissionPreset === "brands" ? "is-selected" : ""}><input type="radio" name="permission-preset" checked={permissionPreset === "brands"} onChange={() => setPermissionPreset("brands")} /><i><UsersThree size={19} weight="duotone" /></i><span><strong>只开放指定品牌</strong><small>客户只能看到下方勾选的品牌素材。</small></span><CheckCircle size={20} weight={permissionPreset === "brands" ? "fill" : "regular"} /></label><label className={permissionPreset === "custom" ? "is-selected" : ""}><input type="radio" name="permission-preset" checked={permissionPreset === "custom"} onChange={() => setPermissionPreset("custom")} /><i><Key size={19} weight="duotone" /></i><span><strong>自定义品牌与扩展素材</strong><small>同时选择品牌以及展会、赞助等扩展素材。</small></span><CheckCircle size={20} weight={permissionPreset === "custom" ? "fill" : "regular"} /></label></div>{permissionPreset !== "all" && <div className="permission-check-groups"><fieldset><legend>可见品牌 <small>{selectedBrands.length} 个已选</small></legend><div>{brandOptions.map((brand) => <label key={brand} className={selectedBrands.includes(brand) ? "is-checked" : ""}><input type="checkbox" checked={selectedBrands.includes(brand)} onChange={() => toggleValue(brand, selectedBrands, setSelectedBrands)} /><span><Check size={14} weight="bold" /></span>{normalizeBrandLabel(brand)}</label>)}</div></fieldset>{permissionPreset === "custom" && <fieldset><legend>扩展素材 <small>{wizardSelectedOther.length} 个已选</small></legend><div>{otherOptions.filter((value) => value !== "No Brand").map((value) => <label key={value} className={wizardSelectedOther.includes(value) ? "is-checked" : ""}><input type="checkbox" checked={wizardSelectedOther.includes(value)} onChange={() => toggleValue(value, selectedOther, setSelectedOther)} /><span><Check size={14} weight="bold" /></span>{value}</label>)}</div></fieldset>}</div>}</div></div>}

                {wizardStep === 3 && <div className="account-confirm-step"><div className="account-wizard-intro"><span>第三步</span><h3>确认账号与权限</h3><p>请检查以下信息，创建后客户即可使用账号登录。</p></div><div className="account-confirm-card"><div className="account-confirm-user"><i>{initials(accountDraft.name)}</i><span><strong>{accountDraft.name}</strong><small>{accountDraft.email}</small></span><mark>{roleLabels[accountDraft.role]}</mark></div><dl><div><dt>账号有效期</dt><dd>创建后 15 天自动停用</dd></div><div><dt>权限方式</dt><dd>{permissionPreset === "all" ? "开放全部素材" : permissionPreset === "brands" ? "只开放指定品牌" : "自定义品牌与扩展素材"}</dd></div><div><dt>可见品牌</dt><dd>{permissionPreset === "all" ? "全部品牌" : selectedBrands.map(normalizeBrandLabel).join("、") || "无"}</dd></div><div><dt>扩展素材</dt><dd>{permissionPreset === "all" ? "全部扩展素材" : permissionPreset === "custom" ? selectedOther.join("、") || "无" : "无"}</dd></div></dl><p><CheckCircle size={19} weight="fill" /> 账号和权限将在同一次保存中完成，不会产生未配置权限的账号。</p></div></div>}
              </div>
              <footer className="account-wizard-actions"><button className="button button-secondary" type="button" onClick={wizardStep === 1 ? closeModal : () => setWizardStep((wizardStep - 1) as WizardStep)} disabled={submitting}>{wizardStep === 1 ? "取消" : <><ArrowLeft size={17} weight="bold" /> 上一步</>}</button>{wizardStep < 3 ? <button className="button button-primary" type="button" onClick={nextWizardStep}>下一步 <ArrowRight size={17} weight="bold" /></button> : <button className="button button-primary" type="button" onClick={createAccount} disabled={submitting}>{submitting ? <SpinnerGap className="is-spinning" size={17} /> : <UserPlus size={17} weight="bold" />}{submitting ? "正在创建…" : "确认创建账号"}</button>}</footer>
            </section>
          ) : openModal === "edit" && editingUser ? (
            <section className="account-editor-modal" role="dialog" aria-modal="true" aria-labelledby="account-editor-title">
              <header className="account-wizard-heading account-editor-heading">
                <div><span>Customer account management</span><h2 id="account-editor-title">编辑客户账号</h2><small>账号状态、可见权限与密码安全操作集中在这里完成。</small></div>
                <button type="button" onClick={closeModal} disabled={submitting} aria-label="关闭弹窗"><X size={20} weight="bold" /></button>
              </header>
              <div className="account-editor-body">
                <aside className="account-editor-sidebar">
                  <i>{initials(accountEditDraft.name || editingUser.name)}</i>
                  <h3>{accountEditDraft.name || editingUser.name}</h3>
                  <p>{editingUser.email}</p>
                  <mark className={accountEditDraft.disabled ? "is-disabled" : ""}><span />{accountEditDraft.disabled ? "账号已停用" : "账号正常"}</mark>
                  <dl><div><dt>创建时间</dt><dd>{editingUser.createdAt}</dd></div><div><dt>有效期至</dt><dd>{editingUser.expiresAt || "创建后 15 天"}</dd></div><div><dt>权限方式</dt><dd>{editPermissionPreset === "all" ? "全部素材" : "单账号指定"}</dd></div></dl>
                </aside>
                <main className="account-editor-main">
                  {modalError && <div className="permission-error-banner" role="alert"><strong>保存失败</strong><span>{modalError}</span></div>}
                  <section className="account-editor-card">
                    <header><div><UsersThree size={19} weight="duotone" /><span><strong>账号资料与状态</strong><small>邮箱作为登录账号，不支持在此修改。</small></span></div></header>
                    <div className="account-editor-grid">
                      <label>客户姓名<input value={accountEditDraft.name} onChange={(event) => setAccountEditDraft({ ...accountEditDraft, name: event.target.value })} /></label>
                      <label>业务邮箱<input value={editingUser.email} readOnly aria-readonly="true" /></label>
                      <label>客户角色<select value={accountEditDraft.role} onChange={(event) => setAccountEditDraft({ ...accountEditDraft, role: event.target.value as AccountDraft["role"] })}><option value="overseas_customer">海外客户</option><option value="domestic_customer">国内客户</option><option value="service_provider">服务商</option></select></label>
                      <button type="button" className={`account-status-switch ${accountEditDraft.disabled ? "is-disabled" : ""}`} role="switch" aria-checked={accountEditDraft.disabled} onClick={() => setAccountEditDraft({ ...accountEditDraft, disabled: !accountEditDraft.disabled })}><span><Power size={18} weight="bold" /><b>停用此账号</b><small>停用后立即禁止登录并结束现有会话。</small></span><i /></button>
                    </div>
                  </section>

                  <section className="account-editor-card">
                    <header><div><ShieldCheck size={19} weight="duotone" /><span><strong>可见权限</strong><small>保存时会完整替换该账号当前的单独权限。</small></span></div></header>
                    <div className="account-editor-permission-body">
                      <div className="permission-preset-list is-compact">
                        <label className={editPermissionPreset === "all" ? "is-selected" : ""}><input type="radio" name="edit-permission-preset" checked={editPermissionPreset === "all"} onChange={() => switchEditPermissionPreset("all")} /><i><ShieldCheck size={17} /></i><span><strong>开放全部素材</strong><small>为该账号明确开放当前全部范围</small></span><CheckCircle size={18} weight={editPermissionPreset === "all" ? "fill" : "regular"} /></label>
                        <label className={editPermissionPreset === "brands" ? "is-selected" : ""}><input type="radio" name="edit-permission-preset" checked={editPermissionPreset === "brands"} onChange={() => switchEditPermissionPreset("brands")} /><i><UsersThree size={17} /></i><span><strong>指定品牌</strong><small>保留现有勾选，可直接增减品牌</small></span><CheckCircle size={18} weight={editPermissionPreset === "brands" ? "fill" : "regular"} /></label>
                        <label className={editPermissionPreset === "custom" ? "is-selected" : ""}><input type="radio" name="edit-permission-preset" checked={editPermissionPreset === "custom"} onChange={() => switchEditPermissionPreset("custom")} /><i><Key size={17} /></i><span><strong>品牌 + 扩展素材</strong><small>保留现有品牌并增减扩展范围</small></span><CheckCircle size={18} weight={editPermissionPreset === "custom" ? "fill" : "regular"} /></label>
                      </div>
                      {editPermissionPreset !== "all" && <div className="permission-check-groups account-editor-checks"><fieldset><legend>可见品牌 <small>{editSelectedBrands.length} 个已选</small></legend><div>{brandOptions.map((brand) => <label key={brand} className={editSelectedBrands.includes(brand) ? "is-checked" : ""}><input type="checkbox" checked={editSelectedBrands.includes(brand)} onChange={() => toggleValue(brand, editSelectedBrands, setEditSelectedBrands)} /><span><Check size={14} weight="bold" /></span>{normalizeBrandLabel(brand)}</label>)}</div></fieldset>{editPermissionPreset === "custom" && <fieldset><legend>扩展素材 <small>{editorSelectedOther.length} 个已选</small></legend><div>{otherOptions.filter((value) => value !== "No Brand").map((value) => <label key={value} className={editorSelectedOther.includes(value) ? "is-checked" : ""}><input type="checkbox" checked={editorSelectedOther.includes(value)} onChange={() => toggleValue(value, editSelectedOther, setEditSelectedOther)} /><span><Check size={14} weight="bold" /></span>{value}</label>)}</div></fieldset>}</div>}
                    </div>
                  </section>

                  <section className="account-editor-card account-password-card">
                    <header><div><LockKey size={19} weight="duotone" /><span><strong>密码安全</strong><small>原密码经过加密哈希保存，无法查看。</small></span></div></header>
                    <div className="account-editor-password">
                      <div><strong>{temporaryPassword ? "新的临时密码" : "当前登录密码"}</strong><p>{temporaryPassword ? "仅本次显示，请复制后通过安全方式交给客户。" : "需要交付新密码时，请重置一组一次性显示的临时密码。"}</p></div>
                      <div className="account-editor-password-control">
                        <input type={temporaryPassword && showTemporaryPassword ? "text" : "password"} value={temporaryPassword || "password-not-readable"} readOnly aria-label={temporaryPassword ? "新的临时密码" : "当前密码不可查看"} />
                        {temporaryPassword && <button type="button" className="password-visibility-button" onClick={() => setShowTemporaryPassword(!showTemporaryPassword)} aria-label={showTemporaryPassword ? "隐藏临时密码" : "查看临时密码"}>{showTemporaryPassword ? <EyeSlash size={18} /> : <Eye size={18} />}</button>}
                        {temporaryPassword ? <button type="button" className="button button-secondary" onClick={copyTemporaryPassword}><Copy size={17} weight="bold" /> {passwordCopied ? "已复制" : "复制密码"}</button> : <button type="button" className="button button-secondary" onClick={resetEditedPassword} disabled={submitting}><LockKey size={17} weight="bold" /> 重置临时密码</button>}
                      </div>
                    </div>
                  </section>
                </main>
              </div>
              <footer className="account-wizard-actions account-editor-actions"><button className="button button-secondary" type="button" onClick={closeModal} disabled={submitting}>取消</button><button className="button button-primary" type="button" onClick={saveEditedAccount} disabled={submitting}>{submitting ? <SpinnerGap className="is-spinning" size={17} /> : <Check size={17} weight="bold" />}{submitting ? "正在保存…" : "保存账号修改"}</button></footer>
            </section>
          ) : null}
        </div>
      )}
    </section>
  );
}
