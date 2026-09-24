import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  ArrowClockwise,
  Buildings,
  CalendarBlank,
  CaretLeft,
  CaretRight,
  CheckCircle,
  Clock,
  CurrencyDollar,
  DotsThree,
  DownloadSimple,
  FileXls,
  MagnifyingGlass,
  Package,
  ShoppingCartSimple,
  SpinnerGap,
  UserCircle,
  X,
} from "@phosphor-icons/react";
import type { AuthUser } from "../services/auth";
import { AssetImage } from "../components/AssetImage";
import { thumbnailVariantUrl } from "../utils/thumbnails";
import { formatMoney } from "../quotation/quotation";
import { loadCustomerOrders, type CustomerOrder } from "./orderService";

interface Props {
  user: AuthUser;
  onNotify: (message: string) => void;
  embedded?: boolean;
  onContinueShopping?: () => void;
  onReorder?: (order: CustomerOrder) => void;
}

interface CustomerOrderGroup {
  key: string;
  name: string;
  email: string;
  orders: CustomerOrder[];
}

const CUSTOMER_ORDER_PAGE_SIZES = [4, 8, 12] as const;
const DEFAULT_CUSTOMER_ORDER_PAGE_SIZE = 8;

function dateValue(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function orderDate(value: string) {
  const date = dateValue(value);
  return date ? new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date) : value;
}

function compactDate(value: string) {
  const date = dateValue(value);
  return date ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date) : value;
}

function fileSize(value: number) {
  return value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.ceil(value / 1024))} KB`;
}

function customerKey(order: CustomerOrder) {
  return (order.customerEmail || order.customerName).trim().toLocaleLowerCase();
}

export function OrdersPanel({ user, onNotify, embedded = false, onContinueShopping, onReorder }: Props) {
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedCustomerKey, setSelectedCustomerKey] = useState("");
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [detailOpen, setDetailOpen] = useState(true);
  const [customerSearch, setCustomerSearch] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | CustomerOrder["status"]>("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [customerPeriod, setCustomerPeriod] = useState<"all" | "30" | "90" | "year">("all");
  const [customerPage, setCustomerPage] = useState(1);
  const [customerPageSize, setCustomerPageSize] = useState(DEFAULT_CUSTOMER_ORDER_PAGE_SIZE);
  const [successNotice, setSuccessNotice] = useState(() => {
    try {
      const raw = sessionStorage.getItem("kairay.orderSuccess");
      if (!raw) return "";
      sessionStorage.removeItem("kairay.orderSuccess");
      const notice = JSON.parse(raw) as { salespersonName?: string; notificationStatus?: string };
      return notice.notificationStatus === "sent"
        ? `Order placed successfully. ${notice.salespersonName || "Your salesperson"} has been notified.`
        : "Order placed successfully. You can download the saved Excel file below.";
    } catch { return ""; }
  });
  const isAdmin = user.isAdmin;

  const load = () => {
    setLoading(true);
    setError("");
    loadCustomerOrders()
      .then(setOrders)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Orders could not be loaded."))
      .finally(() => setLoading(false));
  };

  useEffect(load, [user.id]);
  const customerGroups = useMemo<CustomerOrderGroup[]>(() => {
    const groups = new Map<string, CustomerOrderGroup>();
    orders.forEach((order) => {
      const key = customerKey(order);
      const group = groups.get(key) || { key, name: order.customerName, email: order.customerEmail, orders: [] };
      group.orders.push(order);
      groups.set(key, group);
    });
    return [...groups.values()].sort((left, right) => {
      const leftTime = dateValue(left.orders[0]?.createdAt || "")?.getTime() || 0;
      const rightTime = dateValue(right.orders[0]?.createdAt || "")?.getTime() || 0;
      return rightTime - leftTime;
    });
  }, [orders]);

  const visibleCustomers = useMemo(() => {
    const needle = customerSearch.trim().toLocaleLowerCase();
    return needle
      ? customerGroups.filter((group) => `${group.name} ${group.email}`.toLocaleLowerCase().includes(needle))
      : customerGroups;
  }, [customerGroups, customerSearch]);

  useEffect(() => {
    if (!visibleCustomers.length) {
      setSelectedCustomerKey("");
      setSelectedOrderId(null);
      return;
    }
    if (!visibleCustomers.some((group) => group.key === selectedCustomerKey)) {
      setSelectedCustomerKey(visibleCustomers[0].key);
    }
  }, [selectedCustomerKey, visibleCustomers]);

  const selectedCustomer = customerGroups.find((group) => group.key === selectedCustomerKey) || null;
  const visibleOrders = useMemo(() => {
    const needle = orderSearch.trim().toLocaleLowerCase();
    return (selectedCustomer?.orders || []).filter((order) => {
      if (needle && ![order.orderNumber, order.title, order.fileName, order.reference]
        .join(" ").toLocaleLowerCase().includes(needle)) return false;
      if (statusFilter !== "all" && order.status !== statusFilter) return false;
      const createdAt = dateValue(order.createdAt);
      if (fromDate && createdAt && createdAt < new Date(`${fromDate}T00:00:00`)) return false;
      if (toDate && createdAt && createdAt > new Date(`${toDate}T23:59:59`)) return false;
      return true;
    });
  }, [fromDate, orderSearch, selectedCustomer, statusFilter, toDate]);

  useEffect(() => {
    if (!visibleOrders.length) {
      setSelectedOrderId(null);
      return;
    }
    if (!visibleOrders.some((order) => order.id === selectedOrderId)) {
      setSelectedOrderId(visibleOrders[0].id);
    }
  }, [selectedOrderId, visibleOrders]);

  const selected = visibleOrders.find((order) => order.id === selectedOrderId) || null;

  const customerVisibleOrders = useMemo(() => {
    const needle = orderSearch.trim().toLocaleLowerCase();
    const now = Date.now();
    return orders.filter((order) => {
      if (needle && ![order.orderNumber, order.title, order.fileName, order.reference]
        .join(" ").toLocaleLowerCase().includes(needle)) return false;
      if (statusFilter !== "all" && order.status !== statusFilter) return false;
      const created = dateValue(order.createdAt)?.getTime() || 0;
      if (customerPeriod === "30" && created < now - 30 * 86400000) return false;
      if (customerPeriod === "90" && created < now - 90 * 86400000) return false;
      if (customerPeriod === "year" && dateValue(order.createdAt)?.getFullYear() !== new Date().getFullYear()) return false;
      return true;
    });
  }, [customerPeriod, orderSearch, orders, statusFilter]);

  useEffect(() => setCustomerPage(1), [customerPeriod, orderSearch, statusFilter]);

  const customerPageCount = Math.max(1, Math.ceil(customerVisibleOrders.length / customerPageSize));
  useEffect(() => {
    setCustomerPage((current) => Math.min(current, customerPageCount));
  }, [customerPageCount]);

  const customerPageOrders = useMemo(() => {
    const start = (customerPage - 1) * customerPageSize;
    return customerVisibleOrders.slice(start, start + customerPageSize);
  }, [customerPage, customerPageSize, customerVisibleOrders]);

  const customerMonthGroups = useMemo(() => {
    const groups = new Map<string, { label: string; orders: CustomerOrder[] }>();
    customerPageOrders.forEach((order) => {
      const date = dateValue(order.createdAt);
      const key = date ? `${date.getFullYear()}-${date.getMonth()}` : "unknown";
      const label = date ? new Intl.DateTimeFormat("en-US", { year: "numeric", month: "long" }).format(date) : "Other orders";
      const group = groups.get(key) || { label, orders: [] };
      group.orders.push(order);
      groups.set(key, group);
    });
    return [...groups.values()];
  }, [customerPageOrders]);

  useEffect(() => {
    if (isAdmin || embedded) return;
    if (!customerPageOrders.length) setSelectedOrderId(null);
    else if (!customerPageOrders.some((order) => order.id === selectedOrderId)) setSelectedOrderId(customerPageOrders[0].id);
  }, [customerPageOrders, embedded, isAdmin, selectedOrderId]);

  const customerSelected = customerPageOrders.find((order) => order.id === selectedOrderId) || customerPageOrders[0] || null;

  const goToCustomerPage = (page: number) => {
    const nextPage = Math.max(1, Math.min(page, customerPageCount));
    const firstOrder = customerVisibleOrders[(nextPage - 1) * customerPageSize];
    setCustomerPage(nextPage);
    setSelectedOrderId(firstOrder?.id || null);
  };

  const handleAdminDownload = (orderId: number) => {
    setOrders((current) => current.map((order) => order.id === orderId
      ? { ...order, status: "confirmed", confirmedAt: order.confirmedAt || new Date().toISOString() }
      : order));
    onNotify("订单已确认，正在下载 Excel。");
    window.setTimeout(() => {
      load();
      window.dispatchEvent(new Event("kairay:pending-orders-changed"));
    }, 900);
  };

  if (!isAdmin && !embedded) {
    return <main className="customer-orders-page">
      {successNotice && <div className="customer-order-success" role="status"><CheckCircle size={24} weight="fill" /><strong>{successNotice}</strong><button type="button" onClick={() => setSuccessNotice("")} aria-label="Dismiss notification"><X size={18} /></button></div>}
      <header className="customer-orders-heading"><div><h1>My orders</h1><p>Review previous orders, download files, or place them again.</p></div><button className="customer-orders-refresh" type="button" onClick={load} disabled={loading} aria-label="Refresh orders"><ArrowClockwise className={loading ? "is-spinning" : ""} size={19} /></button></header>
      {loading ? <div className="orders-state"><SpinnerGap className="is-spinning" size={28} /><span>Loading orders…</span></div>
        : error ? <div className="orders-state is-error"><strong>{error}</strong><button className="button" onClick={load}>Try again</button></div>
        : orders.length ? <div className="customer-orders-workspace">
          <section className="customer-orders-list-pane">
            <div className="customer-orders-toolbar">
              <label><span className="quote-sr-only">Order status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | CustomerOrder["status"])}><option value="all">All statuses</option><option value="new">Submitted</option><option value="confirmed">Confirmed</option></select></label>
              <label><CalendarBlank size={18} /><span className="quote-sr-only">Order period</span><select value={customerPeriod} onChange={(event) => setCustomerPeriod(event.target.value as typeof customerPeriod)}><option value="all">All time</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="year">This year</option></select></label>
              <label className="customer-orders-search"><MagnifyingGlass size={19} /><input value={orderSearch} onChange={(event) => setOrderSearch(event.target.value)} placeholder="Search order number or reference" /></label>
            </div>
            <div className="customer-orders-table-wrap">
              <table className="customer-orders-table">
                <thead><tr><th>Order number</th><th>Order date</th><th>Products</th><th>Quantity</th><th>Amount</th><th>Status</th></tr></thead>
                {customerMonthGroups.map((group) => <tbody key={group.label}>
                  <tr className="customer-order-month"><th colSpan={6}>{group.label}<span>{group.orders.length} {group.orders.length === 1 ? "order" : "orders"}</span></th></tr>
                  {group.orders.map((order) => <tr key={order.id} className={customerSelected?.id === order.id ? "is-selected" : ""} tabIndex={0} onClick={() => setSelectedOrderId(order.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedOrderId(order.id); } }}>
                    <td><strong>{order.orderNumber}</strong></td><td>{orderDate(order.createdAt)}</td><td>{order.productCount}</td><td>{order.totalQuantity.toLocaleString()}</td><td><strong>{formatMoney(order.totalAmountCents, order.currency)}</strong></td>
                    <td><span className={`customer-order-status is-${order.status}`}>{order.status === "confirmed" ? <CheckCircle size={17} weight="fill" /> : <Clock size={17} weight="bold" />}{order.status === "confirmed" ? "Confirmed" : "Submitted"}</span></td>
                  </tr>)}
                </tbody>)}
              </table>
              {!customerVisibleOrders.length && <div className="orders-table-empty"><FileXls size={30} weight="duotone" /><strong>No matching orders</strong><span>Adjust the filters or search terms and try again.</span></div>}
            </div>
            {!!customerVisibleOrders.length && <nav className="customer-orders-pagination" aria-label="Order pages">
              <div className="customer-orders-page-size">
                <label>Per page <select value={customerPageSize} onChange={(event) => { const size = Number(event.target.value); setCustomerPageSize(size); setCustomerPage(1); setSelectedOrderId(customerVisibleOrders[0]?.id || null); }}>{CUSTOMER_ORDER_PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
                <span>{(customerPage - 1) * customerPageSize + 1}–{Math.min(customerPage * customerPageSize, customerVisibleOrders.length)} of {customerVisibleOrders.length}</span>
              </div>
              {customerPageCount > 1 && <div>
                <button type="button" onClick={() => goToCustomerPage(customerPage - 1)} disabled={customerPage === 1} aria-label="Previous order page"><CaretLeft size={17} weight="bold" /></button>
                {Array.from({ length: customerPageCount }, (_, index) => index + 1).map((page) => <button key={page} type="button" className={page === customerPage ? "is-current" : ""} onClick={() => goToCustomerPage(page)} aria-label={`Order page ${page}`} aria-current={page === customerPage ? "page" : undefined}>{page}</button>)}
                <button type="button" onClick={() => goToCustomerPage(customerPage + 1)} disabled={customerPage === customerPageCount} aria-label="Next order page"><CaretRight size={17} weight="bold" /></button>
              </div>}
            </nav>}
          </section>
          {customerSelected && <aside className="customer-order-detail-pane">
            <header><h2>Order details</h2>{onContinueShopping && <button type="button" onClick={onContinueShopping}>Continue shopping <ArrowRight size={18} weight="bold" /></button>}</header>
            <section className="customer-order-meta-card"><dl>
              <div><dt>Order number</dt><dd>{customerSelected.orderNumber}</dd></div><div><dt>Customer</dt><dd>{customerSelected.customerName}</dd></div><div><dt>Salesperson</dt><dd>{customerSelected.salespersonName}</dd></div><div><dt>Order date</dt><dd>{orderDate(customerSelected.createdAt)}</dd></div><div><dt>Status</dt><dd><span className={`customer-order-status is-${customerSelected.status}`}>{customerSelected.status === "confirmed" ? <CheckCircle size={17} weight="fill" /> : <Clock size={17} weight="bold" />}{customerSelected.status === "confirmed" ? "Confirmed" : "Submitted"}</span></dd></div><div><dt>Reference</dt><dd>{customerSelected.reference || "—"}</dd></div>
            </dl></section>
            <section className="customer-order-products"><header><h3>Products</h3><span>{customerSelected.productCount} products · {customerSelected.totalQuantity.toLocaleString()} pcs</span></header>
              {customerSelected.items.length ? <div className="customer-order-products-table"><table><thead><tr><th>#</th><th>Photo</th><th>SKU</th><th>Product</th><th>Qty</th><th>Unit price</th><th>Subtotal</th></tr></thead><tbody>{customerSelected.items.map((item, index) => <tr key={`${item.sku}-${index}`}><td>{index + 1}</td><td>{item.imageUrl ? <AssetImage src={thumbnailVariantUrl(item.imageUrl, "small")} alt="" loading="lazy" /> : <span className="customer-order-no-photo"><Package size={19} /></span>}</td><td>{item.sku}</td><td>{item.name}</td><td>{item.quantity.toLocaleString()}</td><td>{item.unitPriceCents === null ? "Quote" : formatMoney(item.unitPriceCents, customerSelected.currency)}</td><td>{item.amountCents === null ? "—" : formatMoney(item.amountCents, customerSelected.currency)}</td></tr>)}</tbody></table></div>
                : <div className="customer-order-products-empty"><Package size={25} /><span>Product details are not available for this earlier order. The saved order can still be downloaded.</span></div>}
            </section>
            <section className="customer-order-summary" aria-label="Order summary">
              <div className="customer-order-summary-heading"><strong>Order summary</strong><span>Selected order totals</span></div>
              <dl>
                <div><dt>Products</dt><dd>{customerSelected.productCount}</dd></div>
                <div><dt>Quantity</dt><dd>{customerSelected.totalQuantity.toLocaleString()} pcs</dd></div>
                <div className="is-total"><dt>Total</dt><dd>{formatMoney(customerSelected.totalAmountCents, customerSelected.currency)}</dd></div>
              </dl>
            </section>
            <footer>{onReorder && <button type="button" className="customer-order-reorder" disabled={!customerSelected.items.length} onClick={() => onReorder(customerSelected)}><ShoppingCartSimple size={19} />Order again</button>}<a className="customer-order-download" href={customerSelected.downloadUrl} onClick={() => onNotify("Downloading order Excel…")}><DownloadSimple size={19} />Download Excel</a></footer>
          </aside>}
        </div>
        : <div className="orders-state"><FileXls size={42} weight="duotone" /><strong>No orders yet</strong><span>Orders placed from the Product Catalog will appear here.</span></div>}
    </main>;
  }

  return <main className="orders-page is-admin-embedded">
    {loading ? <div className="orders-state orders-workbench-state"><SpinnerGap className="is-spinning" size={28} /><span>正在加载客户订单…</span></div>
      : error ? <div className="orders-state orders-workbench-state is-error"><strong>{error}</strong><button className="button" onClick={load}>重新加载</button></div>
      : orders.length ? <div className={`orders-workbench ${detailOpen && selected ? "has-detail" : ""}`}>
        <aside className="orders-customer-pane">
          <header><div><strong>{user.isSuperAdmin ? "全部客户" : "我的客户"}</strong><em>{customerGroups.length}</em></div></header>
          <label className="orders-search-field"><MagnifyingGlass size={18} weight="bold" /><input value={customerSearch} onChange={(event) => setCustomerSearch(event.target.value)} placeholder="搜索客户名称" /></label>
          <div className="orders-customer-list">
            {visibleCustomers.map((group) => <button key={group.key} type="button" className={selectedCustomerKey === group.key ? "is-active" : ""} onClick={() => { setSelectedCustomerKey(group.key); setSelectedOrderId(group.orders[0]?.id || null); setDetailOpen(true); }}>
              <span className="orders-customer-avatar"><Buildings size={18} weight="duotone" /></span>
              <span><strong>{group.name}</strong><small>最近下单 · {compactDate(group.orders[0]?.createdAt || "")}</small></span>
              <em><strong>{group.orders.length}</strong><small>个订单</small></em>
            </button>)}
            {!visibleCustomers.length && <div className="orders-customer-empty">没有找到客户</div>}
          </div>
        </aside>

        <section className="orders-table-pane">
          <header className="orders-workbench-heading"><div><strong>订单列表</strong><small>{selectedCustomer?.name || "选择客户"}</small></div><button type="button" onClick={load} disabled={loading} aria-label="刷新订单"><ArrowClockwise className={loading ? "is-spinning" : ""} size={18} weight="bold" /></button></header>
          <div className="orders-toolbar">
            <label className="orders-status-field"><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | CustomerOrder["status"])} aria-label="订单状态"><option value="all">全部状态</option><option value="new">新订单</option><option value="confirmed">已确认</option></select></label>
            <label className="orders-date-field"><CalendarBlank size={17} weight="bold" /><input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} aria-label="开始日期" /><span>→</span><input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} aria-label="结束日期" /></label>
            <label className="orders-search-field"><MagnifyingGlass size={18} weight="bold" /><input value={orderSearch} onChange={(event) => setOrderSearch(event.target.value)} placeholder="搜索订单号、备注" /></label>
          </div>
          <p className="orders-result-count">共 {visibleOrders.length} 条订单</p>
          <div className="orders-table-scroll">
            <table className="orders-data-table">
              <thead><tr><th>订单号</th><th>下单时间</th><th>款数</th><th>数量</th><th>金额</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>{visibleOrders.map((order) => <tr key={order.id} className={detailOpen && selectedOrderId === order.id ? "is-selected" : ""} onClick={() => { setSelectedOrderId(order.id); setDetailOpen(true); }}>
                <td><strong>{order.orderNumber}</strong><small>{order.title || order.reference || "客户订单"}</small></td>
                <td>{orderDate(order.createdAt)}</td>
                <td>{order.productCount} 款</td>
                <td>{order.totalQuantity.toLocaleString()} 件</td>
                <td><strong>{formatMoney(order.totalAmountCents, order.currency)}</strong></td>
                <td><span className={`order-status-chip is-${order.status}`}>{order.status === "confirmed" ? "已确认" : "新订单"}</span></td>
                <td><button type="button" aria-label={`查看 ${order.orderNumber}`} onClick={(event) => { event.stopPropagation(); setSelectedOrderId(order.id); setDetailOpen(true); }}><DotsThree size={20} weight="bold" /></button></td>
              </tr>)}</tbody>
            </table>
            {!visibleOrders.length && <div className="orders-table-empty"><FileXls size={30} weight="duotone" /><strong>没有符合条件的订单</strong><span>调整日期或搜索条件后再试。</span></div>}
          </div>
        </section>

        {detailOpen && selected && <aside className="orders-detail-pane">
          <header><strong>订单详情</strong><button type="button" aria-label="关闭订单详情" onClick={() => setDetailOpen(false)}><X size={20} /></button></header>
          <section><h3>客户信息</h3><div className="orders-detail-customer"><span><Buildings size={20} weight="duotone" /></span><div><strong>{selected.customerName}</strong><small>{selected.customerEmail}</small></div></div>
            <dl>{selected.company && <div><dt>公司</dt><dd>{selected.company}</dd></div>}{selected.contact && <div><dt>联系方式</dt><dd>{selected.contact}</dd></div>}{selected.reference && <div><dt>参考号</dt><dd>{selected.reference}</dd></div>}</dl></section>
          <section><h3>销售信息</h3><dl className="is-icon-list"><div><dt><UserCircle size={18} />业务员</dt><dd>{selected.salespersonName}</dd></div><div><dt><CalendarBlank size={18} />下单时间</dt><dd>{orderDate(selected.createdAt)}</dd></div><div><dt><FileXls size={18} />订单号</dt><dd>{selected.orderNumber}</dd></div><div><dt>订单状态</dt><dd><span className={`order-status-chip is-${selected.status}`}>{selected.status === "confirmed" ? "已确认" : "新订单"}</span></dd></div></dl></section>
          <section><h3>订单汇总</h3><div className="orders-detail-summary"><div><Package size={20} weight="duotone" /><small>款数</small><strong>{selected.productCount} 款</strong></div><div><Package size={20} weight="duotone" /><small>数量</small><strong>{selected.totalQuantity.toLocaleString()} 件</strong></div><div><CurrencyDollar size={20} weight="duotone" /><small>金额</small><strong>{formatMoney(selected.totalAmountCents, selected.currency)}</strong></div></div></section>
          <section className="orders-detail-file"><h3>订单文件</h3><div><span><FileXls size={25} weight="duotone" /></span><p><strong>{selected.fileName}</strong><small>{fileSize(selected.fileSize)} · {compactDate(selected.createdAt)}</small></p></div><a className="button button-primary" href={selected.downloadUrl} onClick={() => handleAdminDownload(selected.id)}><DownloadSimple size={18} />下载 Excel</a></section>
        </aside>}
      </div>
      : <div className="orders-state orders-workbench-state"><FileXls size={42} weight="duotone" /><strong>还没有客户订单</strong><span>{user.isSuperAdmin ? "所有客户提交的订单都会显示在这里。" : "你创建的客户下单后会显示在这里。"}</span></div>}
  </main>;
}
