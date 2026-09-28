export interface CustomerOrderItem {
  sku: string;
  name: string;
  quantity: number;
  unitPriceCents: number | null;
  amountCents: number | null;
  imageUrl: string;
}

export interface CustomerOrder {
  id: number;
  orderNumber: string;
  customerName: string;
  customerEmail: string;
  salespersonName: string;
  title: string;
  company: string;
  contact: string;
  reference: string;
  currency: string;
  productCount: number;
  totalQuantity: number;
  totalAmountCents: number;
  unpricedCount: number;
  items: CustomerOrderItem[];
  fileName: string;
  fileSize: number;
  notificationStatus: string;
  status: "new" | "confirmed";
  confirmedAt: string;
  createdAt: string;
  downloadUrl: string;
}

interface ApiOrder {
  id: number;
  order_number: string;
  customer_name: string;
  customer_email: string;
  salesperson_name: string;
  title: string;
  company: string;
  contact: string;
  reference: string;
  currency: string;
  product_count: number;
  total_quantity: number;
  total_amount_cents: number;
  unpriced_count: number;
  items?: Array<{
    sku: string;
    name: string;
    quantity: number;
    unit_price_cents?: number | null;
    amount_cents?: number | null;
    image_url?: string;
  }>;
  file_name: string;
  file_size: number;
  notification_status: string;
  status?: string;
  confirmed_at?: string;
  created_at: string;
  download_url: string;
}

function mapOrder(order: ApiOrder): CustomerOrder {
  return {
    id: order.id,
    orderNumber: order.order_number,
    customerName: order.customer_name,
    customerEmail: order.customer_email,
    salespersonName: order.salesperson_name,
    title: order.title,
    company: order.company,
    contact: order.contact,
    reference: order.reference,
    currency: order.currency,
    productCount: order.product_count,
    totalQuantity: order.total_quantity,
    totalAmountCents: order.total_amount_cents,
    unpricedCount: order.unpriced_count,
    items: (order.items || []).map((item) => ({
      sku: item.sku,
      name: item.name,
      quantity: item.quantity,
      unitPriceCents: item.unit_price_cents ?? null,
      amountCents: item.amount_cents ?? null,
      imageUrl: item.image_url || "",
    })),
    fileName: order.file_name,
    fileSize: order.file_size,
    notificationStatus: order.notification_status,
    status: order.status === "confirmed" ? "confirmed" : "new",
    confirmedAt: order.confirmed_at || "",
    createdAt: order.created_at,
    downloadUrl: order.download_url,
  };
}

async function errorMessage(response: Response, fallback: string) {
  if (response.headers.get("content-type")?.includes("application/json")) {
    const payload = await response.json() as { detail?: string };
    return payload.detail || fallback;
  }
  return fallback;
}

export async function loadCustomerOrders(): Promise<CustomerOrder[]> {
  const response = await fetch("/api/orders", { headers: { Accept: "application/json" }, credentials: "include" });
  if (!response.ok) throw new Error(await errorMessage(response, "Orders could not be loaded."));
  const payload = await response.json() as { orders: ApiOrder[] };
  return payload.orders.map(mapOrder);
}

export async function loadPendingCustomerOrderCount(): Promise<number> {
  const response = await fetch("/api/orders/pending-count", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Pending orders could not be loaded."));
  const payload = await response.json() as { pending_count?: number };
  return Math.max(0, Number(payload.pending_count || 0));
}

export async function loadCustomerOrder(orderId: number): Promise<CustomerOrder> {
  const response = await fetch(`/api/orders/${orderId}`, { headers: { Accept: "application/json" }, credentials: "include" });
  if (!response.ok) throw new Error(await errorMessage(response, "The order could not be loaded."));
  const payload = await response.json() as { order: ApiOrder };
  return mapOrder(payload.order);
}

export async function submitCustomerOrder(input: {
  idempotencyKey: string;
  excel: Blob;
  excelName: string;
  title: string;
  company: string;
  contact: string;
  reference: string;
  currency: string;
  productCount: number;
  totalQuantity: number;
  totalAmountCents: number;
  unpricedCount: number;
  items: CustomerOrderItem[];
}): Promise<{ order: CustomerOrder; notificationWarning?: string }> {
  const form = new FormData();
  form.set("idempotency_key", input.idempotencyKey);
  form.set("title", input.title);
  form.set("company", input.company);
  form.set("contact", input.contact);
  form.set("reference", input.reference);
  form.set("currency", input.currency);
  form.set("product_count", String(input.productCount));
  form.set("total_quantity", String(input.totalQuantity));
  form.set("total_amount_cents", String(input.totalAmountCents));
  form.set("unpriced_count", String(input.unpricedCount));
  form.set("items_json", JSON.stringify(input.items));
  form.set("excel_file", input.excel, input.excelName);
  const response = await fetch("/api/orders", {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await errorMessage(response, "The order could not be submitted."));
  const payload = await response.json() as { order: ApiOrder; notification_warning?: string };
  return { order: mapOrder(payload.order), notificationWarning: payload.notification_warning };
}
