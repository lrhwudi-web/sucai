import {
  Fragment,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Archive,
  ArrowsDownUp,
  CaretLeft,
  CaretRight,
  CheckCircle,
  GridFour,
  Heart,
  Rows,
  SpinnerGap,
  X,
} from "@phosphor-icons/react";
import { AdminPanel } from "./admin/AdminPanel";
import { SuperAdminPanel } from "./admin/SuperAdminPanel";
import { OrdersPanel } from "./orders/OrdersPanel";
import { loadPendingCustomerOrderCount } from "./orders/orderService";
import { FilterSidebar } from "./components/FilterSidebar";
import { Header } from "./components/Header";
import { LandingPage } from "./components/LandingPage";
import { ProductSearch } from "./components/ProductSearch";
import { ProductCard } from "./components/ProductCard";
import { ProductDrawer } from "./components/ProductDrawer";
import { apiEnabled, getSession, logoutCustomer, type AuthUser } from "./services/auth";
import {
  SessionExpiredError,
  getProductDriveCopyStatus,
  loadProductDetail,
  loadProducts,
  loadThemeOptions,
  prepareProductDriveCopy,
  reportMissingSkus,
  setProductCover,
  setProductFavorite,
  setProductThemes,
} from "./services/materials";
import {
  DEFAULT_THEME_OPTIONS,
  type MaterialAsset,
  type MaterialProduct,
  type ProductFilters,
  type SortMode,
  type ThemeOption,
  type ViewMode,
} from "./types";
import { parseCatalogueSearch } from "./utils/catalogueSearch";
import { CatalogSheet } from "./quotation/CatalogSheet";
import { useQuotation } from "./quotation/useQuotation";
import { arrangeProducts, catalogDraftFingerprint, useCatalogOrder } from "./quotation/catalogOrder";
import { emptyLine, isQuotable, MAX_QUOTE_PRODUCTS, setQuoteSelection, type QuoteLine } from "./quotation/quotation";
import "./quotation/quotation.css";

const emptyFilters: ProductFilters = {
  brand: [],
  category: [],
  theme: [],
  other: [],
  material: "",
  assetKind: "",
  permission: "",
};

interface DriveJob {
  sku: string;
  progress: number;
  complete: boolean;
  expiresAt?: string;
}

type AppView = "landing" | "catalogue" | "quotation" | "orders" | "admin" | "super-admin";

const LIST_PAGE_SIZE = 20;
const FILTER_PANEL_DEFAULT_WIDTH = 436;
const FILTER_PANEL_MIN_WIDTH = 300;
const FILTER_PANEL_MAX_WIDTH = 600;
const FILTER_PANEL_STORAGE_KEY = "kairay.assetFilters.width";

function clampFilterPanelWidth(width: number) {
  return Math.min(FILTER_PANEL_MAX_WIDTH, Math.max(FILTER_PANEL_MIN_WIDTH, Math.round(width)));
}

function loadFilterPanelWidth() {
  try {
    const saved = Number(window.localStorage.getItem(FILTER_PANEL_STORAGE_KEY));
    return Number.isFinite(saved) && saved > 0
      ? clampFilterPanelWidth(saved)
      : FILTER_PANEL_DEFAULT_WIDTH;
  } catch {
    return FILTER_PANEL_DEFAULT_WIDTH;
  }
}

function viewFromHash(): AppView {
  if (window.location.hash === "#super-admin") return "super-admin";
  if (window.location.hash === "#admin") return "admin";
  if (window.location.hash === "#catalogue") return "catalogue";
  if (window.location.hash === "#quotation") return "quotation";
  if (window.location.hash === "#orders") return "orders";
  return "landing";
}

export function App() {
  const [activeView, setActiveView] = useState<AppView>(viewFromHash);
  const [products, setProducts] = useState<MaterialProduct[]>([]);
  const [themeOptions, setThemeOptions] = useState<ThemeOption[]>(DEFAULT_THEME_OPTIONS);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [catalogueReady, setCatalogueReady] = useState(false);
  const [libraryRefresh, setLibraryRefresh] = useState(0);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [sessionLoading, setSessionLoading] = useState(apiEnabled());
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<ProductFilters>(emptyFilters);
  const [favoriteOnly, setFavoriteOnly] = useState(false);
  const [sort, setSort] = useState<SortMode>("newest");
  const [view, setView] = useState<ViewMode>(() => {
    try { return localStorage.getItem("kairay.assetLibrary.layout") === "list" ? "list" : "grid"; } catch { return "grid"; }
  });
  const [listPage, setListPage] = useState(1);
  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [driveJob, setDriveJob] = useState<DriveJob | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [pendingNotificationCount, setPendingNotificationCount] = useState(0);
  const [batchNotificationState, setBatchNotificationState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [filterPanelWidth, setFilterPanelWidth] = useState(loadFilterPanelWidth);
  const [resizingFilters, setResizingFilters] = useState(false);
  const filterPanelWidthRef = useRef(filterPanelWidth);
  const filterResizeRef = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null);
  const filterResizeCleanupRef = useRef<(() => void) | null>(null);
  const reportedBatchRef = useRef("");
  const quotation = useQuotation(currentUser ? `${currentUser.id}:${currentUser.email}` : "");
  const catalogOrder = useCatalogOrder(currentUser?.id ?? null);
  const orderedCatalogProducts = useMemo(() => arrangeProducts(products, catalogOrder.skuOrder), [products, catalogOrder.skuOrder]);
  const catalogTemplateKey = useMemo(() => catalogDraftFingerprint(catalogOrder.draft), [catalogOrder.draft]);
  const quoteSelected = new Set(quotation.draft.order);
  const toggleQuote = (skus: string[], selected: boolean) => {
    const valid = new Set(products.filter(isQuotable).map((p) => p.sku));
    const allowed = skus.filter((sku) => valid.has(sku));
    if (selected && new Set([...quotation.draft.order, ...allowed]).size > MAX_QUOTE_PRODUCTS) {
      setToast(`Each catalog supports up to ${MAX_QUOTE_PRODUCTS} products. Select a smaller group.`);
      return;
    }
    quotation.update((draft) => setQuoteSelection(draft, allowed, selected));
  };
  const editQuote = (sku: string, patch: Partial<QuoteLine>) => {
    if (patch.quantity && Number(patch.quantity) > 0 && !quoteSelected.has(sku) && quotation.draft.order.length >= MAX_QUOTE_PRODUCTS) {
      setToast(`Each catalog supports up to ${MAX_QUOTE_PRODUCTS} products.`); return;
    }
    quotation.update((draft) => ({ ...draft,
      order: patch.quantity && Number(patch.quantity) > 0 ? [...new Set([...draft.order, sku])] : draft.order,
      lines: { ...draft.lines, [sku]: { ...(draft.lines[sku] || emptyLine()), ...patch } },
    }));
  };

  useEffect(() => {
    if (!currentUser || !quotation.ready || !catalogOrder.draft || catalogOrder.loading) return;
    quotation.applyManagedTemplate(catalogOrder.draft, catalogTemplateKey, !currentUser.isAdmin);
  }, [catalogOrder.draft, catalogOrder.loading, catalogTemplateKey, currentUser, quotation.applyManagedTemplate, quotation.ready]);

  useEffect(() => {
    if (!apiEnabled()) {
      setSessionLoading(false);
      return;
    }
    let mounted = true;
    getSession()
      .then((user) => {
        if (!mounted) return;
        setCurrentUser(user);
        const requestedView = viewFromHash();
        if (!user && requestedView !== "landing") {
          if (requestedView !== "quotation" && requestedView !== "orders") window.location.hash = "";
          setActiveView("landing");
        } else if (user && requestedView === "landing") {
          window.location.hash = "catalogue";
          setActiveView("catalogue");
        } else if (user && requestedView === "admin" && !user.isAdmin) {
          window.location.hash = "catalogue";
          setActiveView("catalogue");
          setToast("Administrator access is required.");
        } else if (user && requestedView === "super-admin" && !user.isSuperAdmin) {
          window.location.hash = user.isAdmin ? "admin" : "catalogue";
          setActiveView(user.isAdmin ? "admin" : "catalogue");
          setToast("Super administrator access is required.");
        }
      })
      .catch((error) => {
        if (!mounted) return;
        setCurrentUser(null);
        setToast(error instanceof Error ? error.message : "We could not connect to the account service.");
        if (viewFromHash() !== "landing") {
          if (viewFromHash() !== "quotation" && viewFromHash() !== "orders") window.location.hash = "";
          setActiveView("landing");
        }
      })
      .finally(() => {
        if (mounted) setSessionLoading(false);
      });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!currentUser?.isAdmin) {
      setPendingNotificationCount(0);
      return;
    }

    let cancelled = false;
    const refreshNotifications = () => {
      loadPendingCustomerOrderCount()
        .then((count) => {
          if (!cancelled) setPendingNotificationCount(count);
        })
        .catch(() => undefined);
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refreshNotifications();
    };

    refreshNotifications();
    const interval = window.setInterval(refreshNotifications, 30_000);
    window.addEventListener("focus", refreshNotifications);
    window.addEventListener("kairay:pending-orders-changed", refreshNotifications);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshNotifications);
      window.removeEventListener("kairay:pending-orders-changed", refreshNotifications);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [currentUser?.id, currentUser?.isAdmin]);

  useEffect(() => {
    if (!currentUser || (activeView !== "catalogue" && activeView !== "quotation")) return;
    let mounted = true;
    setLoading(true);
    setCatalogueReady(false);
    setLoadError("");
    Promise.all([
      loadProducts((partialProducts) => {
        if (!mounted) return;
        setProducts(partialProducts);
        setLoading(false);
      }),
      loadThemeOptions(),
    ])
      .then(([result, loadedThemeOptions]) => {
        if (!mounted) return;
        setProducts(result.products);
        setThemeOptions(loadedThemeOptions);
        setCatalogueReady(true);
      })
      .catch((error) => {
        if (!mounted) return;
        if (error instanceof SessionExpiredError) {
          setCurrentUser(null);
          window.location.hash = "";
          setActiveView("landing");
          setToast(error.message);
          return;
        }
        setLoadError(error instanceof Error ? error.message : "The product library could not be loaded.");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, [activeView, currentUser, libraryRefresh]);

  useEffect(() => {
    const syncViewFromHash = () => {
      const nextView = viewFromHash();
      if (!sessionLoading && nextView !== "landing" && !currentUser) {
        if (nextView !== "quotation" && nextView !== "orders") window.location.hash = "";
        setActiveView("landing");
        return;
      }
      if (nextView === "admin" && currentUser && !currentUser.isAdmin) {
        window.location.hash = "catalogue";
        setActiveView("catalogue");
        setToast("Administrator access is required.");
        return;
      }
      if (nextView === "super-admin" && currentUser && !currentUser.isSuperAdmin) {
        window.location.hash = currentUser.isAdmin ? "admin" : "catalogue";
        setActiveView(currentUser.isAdmin ? "admin" : "catalogue");
        setToast("Super administrator access is required.");
        return;
      }
      setActiveView(nextView);
    };
    window.addEventListener("hashchange", syncViewFromHash);
    return () => window.removeEventListener("hashchange", syncViewFromHash);
  }, [currentUser, sessionLoading]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    if (activeView !== "catalogue" || !selectedSku) return;
    const target = products.find((product) => product.sku === selectedSku);
    if (!target || target.detailsLoaded) return;
    let mounted = true;
    loadProductDetail(selectedSku)
      .then((detail) => {
        if (!mounted) return;
        setProducts((current) => current.map((product) => product.sku === detail.sku ? detail : product));
      })
      .catch((error) => {
        if (!mounted) return;
        if (error instanceof SessionExpiredError) {
          setCurrentUser(null);
          window.location.hash = "";
          setActiveView("landing");
        }
        setToast(error instanceof Error ? error.message : "The product details could not be loaded.");
      });
    return () => { mounted = false; };
  }, [activeView, products, selectedSku]);

  const parsedSearch = useMemo(() => parseCatalogueSearch(search), [search]);
  const batchMissingSkus = useMemo(() => {
    if (!parsedSearch.isBatchSkuSearch) return [];
    const availableSkus = new Set(products.map((product) => product.sku.toUpperCase()));
    return parsedSearch.skuOrder.filter((sku) => !availableSkus.has(sku));
  }, [parsedSearch, products]);
  const batchMissingKey = batchMissingSkus.join("\n");
  const exactSkuProduct = useMemo(() => {
    if (parsedSearch.isBatchSkuSearch) return null;
    const needle = parsedSearch.normalizedText;
    return needle ? products.find((product) => product.sku.toLowerCase() === needle) || null : null;
  }, [products, parsedSearch]);
  const relatedSetCode = exactSkuProduct?.setCode || "";

  const visibleProducts = useMemo(() => {
    const needle = parsedSearch.normalizedText;
    const hasProductFilters = Boolean(
      filters.brand.length
      || filters.category.length
      || filters.theme.length
      || filters.assetKind
      || filters.material
      || filters.permission,
    );
    const filtered = products.filter((product) => {
      if (parsedSearch.isBatchSkuSearch) return parsedSearch.skuSet.has(product.sku.toUpperCase());
      const searchText = [product.sku, product.name, product.brand, product.category, product.otherCategory, product.drivePath]
        .join(" ")
        .toLowerCase();
      const isRelatedSetProduct = Boolean(relatedSetCode && product.setCode === relatedSetCode);
      if (!parsedSearch.isBatchSkuSearch && needle && !searchText.includes(needle) && !isRelatedSetProduct) return false;
      if (favoriteOnly && !product.isFavorite) return false;

      const matchesOtherCollection = Boolean(
        product.otherCategory
        && filters.other.length
        && filters.other.includes(product.otherCategory),
      );
      if (product.otherCategory) {
        return matchesOtherCollection || (!filters.other.length && !hasProductFilters);
      }

      const matchesProductFilters = (
        (!filters.brand.length || filters.brand.includes(product.brand))
        && (!filters.category.length || filters.category.includes(product.category))
        && (!filters.theme.length || filters.theme.some((theme) => product.themes.includes(theme)))
        && (!filters.assetKind || (product.assetTypes || []).includes(filters.assetKind))
        && (!filters.material || product.material === filters.material)
        && (!filters.permission || product.permission === filters.permission)
      );
      if (!matchesProductFilters) return false;
      return hasProductFilters || !filters.other.length;
    });
    return [...filtered].sort((a, b) => {
      if (parsedSearch.isBatchSkuSearch) {
        return parsedSearch.skuOrder.indexOf(a.sku.toUpperCase()) - parsedSearch.skuOrder.indexOf(b.sku.toUpperCase());
      }
      if (exactSkuProduct) {
        if (a.sku === exactSkuProduct.sku) return -1;
        if (b.sku === exactSkuProduct.sku) return 1;
      }
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "category") return a.category.localeCompare(b.category) || a.name.localeCompare(b.name);
      if (sort === "sku") return a.sku.localeCompare(b.sku, undefined, { numeric: true });
      if (sort === "assets") return (b.assetCount ?? b.assets.length) - (a.assetCount ?? a.assets.length);
      return (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0);
    });
  }, [products, filters, favoriteOnly, sort, exactSkuProduct, relatedSetCode, parsedSearch]);

  useEffect(() => {
    if (activeView !== "catalogue" || !catalogueReady || !currentUser || !parsedSearch.isBatchSkuSearch || !batchMissingSkus.length) {
      reportedBatchRef.current = "";
      setBatchNotificationState("idle");
      return;
    }
    const signature = `${currentUser.id}:${batchMissingKey}`;
    if (reportedBatchRef.current === signature) return;
    let cancelled = false;
    const timeout = window.setTimeout(() => {
      reportedBatchRef.current = signature;
      setBatchNotificationState("sending");
      reportMissingSkus(batchMissingSkus, parsedSearch.skuOrder.length)
        .then((result) => {
          if (cancelled) return;
          setBatchNotificationState("sent");
          setToast(result.duplicate
            ? `未搜索到的 ${batchMissingSkus.length} 个 SKU 已提醒管理员，无需重复发送。`
            : `未搜索到的 ${batchMissingSkus.length} 个 SKU 已发送给${result.recipientName}添加。`);
        })
        .catch((caught) => {
          if (cancelled) return;
          setBatchNotificationState("error");
          setToast(caught instanceof Error ? caught.message : "未找到的 SKU 暂时无法通知管理员。");
        });
    }, 700);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [activeView, batchMissingKey, batchMissingSkus, catalogueReady, currentUser, parsedSearch.isBatchSkuSearch, parsedSearch.skuOrder.length]);

  useEffect(() => {
    if (selectedSku && !visibleProducts.some((product) => product.sku === selectedSku)) {
      setSelectedSku(null);
    }
  }, [selectedSku, visibleProducts]);

  const listPageCount = Math.max(1, Math.ceil(visibleProducts.length / LIST_PAGE_SIZE));
  const currentListPage = Math.min(listPage, listPageCount);
  const pageStart = (currentListPage - 1) * LIST_PAGE_SIZE;
  const displayedProducts = view === "list"
    ? visibleProducts.slice(pageStart, pageStart + LIST_PAGE_SIZE)
    : visibleProducts;
  const exactSkuIndex = exactSkuProduct
    ? displayedProducts.findIndex((product) => product.sku === exactSkuProduct.sku)
    : -1;
  const relatedSetsStartIndex = exactSkuIndex >= 0 && relatedSetCode
    ? displayedProducts.findIndex((product, index) => (
        index > exactSkuIndex
        && product.sku !== exactSkuProduct?.sku
        && product.setCode === relatedSetCode
      ))
    : -1;
  const listPageItems = useMemo<(number | string)[]>(() => {
    if (listPageCount <= 7) {
      return Array.from({ length: listPageCount }, (_, index) => index + 1);
    }

    const pages = [...new Set([1, currentListPage - 1, currentListPage, currentListPage + 1, listPageCount])]
      .filter((page) => page >= 1 && page <= listPageCount)
      .sort((a, b) => a - b);
    const items: (number | string)[] = [];
    pages.forEach((page, index) => {
      const previousPage = pages[index - 1];
      if (previousPage && page - previousPage > 1) items.push(`ellipsis-${previousPage}`);
      items.push(page);
    });
    return items;
  }, [currentListPage, listPageCount]);

  useEffect(() => {
    setListPage(1);
  }, [search, filters, favoriteOnly, sort]);

  useEffect(() => {
    if (listPage > listPageCount) setListPage(listPageCount);
  }, [listPage, listPageCount]);

  const selectedProduct = products.find((product) => product.sku === selectedSku) || null;
  const favoriteCount = products.filter((product) => product.isFavorite).length;

  const updateFilterPanelWidth = (width: number, persist = false) => {
    const nextWidth = clampFilterPanelWidth(width);
    filterPanelWidthRef.current = nextWidth;
    setFilterPanelWidth(nextWidth);
    if (persist) {
      try {
        window.localStorage.setItem(FILTER_PANEL_STORAGE_KEY, String(nextWidth));
      } catch {
        // The panel still resizes when browser storage is unavailable.
      }
    }
  };

  const beginFilterResize = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    filterResizeCleanupRef.current?.();
    filterResizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: filterPanelWidthRef.current,
    };
    document.body.classList.add("is-resizing-filters");
    setResizingFilters(true);

    const cleanup = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", finishPointerResize);
      window.removeEventListener("pointercancel", finishPointerResize);
      filterResizeCleanupRef.current = null;
    };
    const handlePointerMove = (pointerEvent: PointerEvent) => {
      const resize = filterResizeRef.current;
      if (!resize || resize.pointerId !== pointerEvent.pointerId) return;
      updateFilterPanelWidth(resize.startWidth + pointerEvent.clientX - resize.startX);
    };
    const finishPointerResize = (pointerEvent: PointerEvent) => {
      const resize = filterResizeRef.current;
      if (!resize || resize.pointerId !== pointerEvent.pointerId) return;
      cleanup();
      filterResizeRef.current = null;
      document.body.classList.remove("is-resizing-filters");
      setResizingFilters(false);
      updateFilterPanelWidth(filterPanelWidthRef.current, true);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", finishPointerResize);
    window.addEventListener("pointercancel", finishPointerResize);
    filterResizeCleanupRef.current = cleanup;
    event.preventDefault();
  };

  const resizeFiltersWithKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const step = event.shiftKey ? 32 : 16;
    const nextWidth = event.key === "ArrowLeft"
      ? filterPanelWidthRef.current - step
      : event.key === "ArrowRight"
        ? filterPanelWidthRef.current + step
        : event.key === "Home"
          ? FILTER_PANEL_MIN_WIDTH
          : event.key === "End"
            ? FILTER_PANEL_MAX_WIDTH
            : null;
    if (nextWidth === null) return;
    event.preventDefault();
    updateFilterPanelWidth(nextWidth, true);
  };

  const resetFilterPanelWidth = () => {
    updateFilterPanelWidth(FILTER_PANEL_DEFAULT_WIDTH, true);
  };

  const updateFilter = (key: keyof ProductFilters, value: string | string[]) => {
    setSelectedSku(null);
    setFilters((current) => {
      if (key === "other") {
        const nextOther = value as string[];
        return nextOther.length
          ? { ...emptyFilters, other: nextOther }
          : { ...current, other: [] };
      }
      if (key === "brand") {
        return { ...current, brand: value as string[], category: [], theme: [], assetKind: "", other: [] };
      }
      if (key === "category") {
        return { ...current, category: value as string[], theme: [], assetKind: "", other: [] };
      }
      return { ...current, [key]: value, other: [] };
    });
  };

  const resetFilters = () => {
    setSelectedSku(null);
    setFilters(emptyFilters);
  };

  const changeView = (nextView: ViewMode) => {
    setView(nextView);
    try { localStorage.setItem("kairay.assetLibrary.layout", nextView); } catch { /* The view still works without storage. */ }
  };

  const goToListPage = (page: number) => {
    setListPage(page);
    document.querySelector(".catalogue-toolbar")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const toggleProductFavorite = async (product: MaterialProduct) => {
    const nextValue = !product.isFavorite;
    setProducts((current) => current.map((item) => item.sku === product.sku ? { ...item, isFavorite: nextValue } : item));
    if (favoriteOnly && !nextValue && selectedSku === product.sku) setSelectedSku(null);
    try {
      const saved = await setProductFavorite(product.sku, nextValue);
      setProducts((current) => current.map((item) => item.sku === product.sku ? { ...item, isFavorite: saved } : item));
      setToast(saved ? `${product.sku} added to your favorites.` : `${product.sku} removed from your favorites.`);
    } catch (error) {
      setProducts((current) => current.map((item) => item.sku === product.sku ? { ...item, isFavorite: Boolean(product.isFavorite) } : item));
      setToast(error instanceof Error ? error.message : "Your favorites could not be updated.");
    }
  };

  const updateProductCover = async (product: MaterialProduct, asset: MaterialAsset) => {
    const coverId = await setProductCover(product.sku, asset.id);
    setProducts((current) => current.map((item) => {
      if (item.sku !== product.sku) return item;
      const selectedCover = item.assets.find((candidate) => candidate.id === coverId) || asset;
      return {
        ...item,
        coverId,
        assets: [selectedCover, ...item.assets.filter((candidate) => candidate.id !== coverId)],
      };
    }));
    setToast(`${product.sku} cover image updated.`);
  };

  const updateProductThemes = async (product: MaterialProduct, themes: string[]) => {
    await setProductThemes(product.sku, themes);
    const labels = themeOptions
      .filter((option) => themes.includes(option.id))
      .map((option) => option.label);
    setProducts((current) => current.map((item) => (
      item.sku === product.sku ? { ...item, themes: labels } : item
    )));
    setToast(`${product.sku} themes updated.`);
  };

  const openProductInDrive = async (product: MaterialProduct) => {
    setDriveJob({ sku: product.sku, progress: 5, complete: false });
    setToast(`Preparing ${product.sku} in Google Drive…`);
    if (!apiEnabled()) {
      setDriveJob(null);
      setToast("Open in Drive requires a connected account.");
      return;
    }
    const driveWindow = window.open("about:blank", "_blank");
    if (driveWindow) {
      driveWindow.opener = null;
      driveWindow.document.title = `Preparing ${product.sku} · Kairay Golf`;
      driveWindow.document.body.textContent = `Preparing ${product.sku} in Google Drive…`;
      driveWindow.document.body.style.cssText = "margin:0;min-height:100vh;display:grid;place-items:center;background:#fffaf5;color:#74171c;font:600 18px system-ui,sans-serif";
    }
    try {
      let state = await prepareProductDriveCopy(product.sku);
      if (!state.job_id) throw new Error("The Drive copy job did not return an ID.");
      const jobId = state.job_id;
      for (let attempt = 0; attempt < 120 && state.state !== "ready" && state.state !== "error"; attempt += 1) {
        setDriveJob({ sku: product.sku, progress: state.progress || 0, complete: false });
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        state = await getProductDriveCopyStatus(product.sku, jobId);
      }
      if (state.state === "error") throw new Error(state.error || "The Drive folder could not be created.");
      if (state.state !== "ready") throw new Error("The Drive copy is taking too long. Please try again.");
      if (!state.folder_url) throw new Error("Google Drive did not return the shared folder link.");
      setDriveJob({ sku: product.sku, progress: 100, complete: true, expiresAt: state.expires_at });
      setToast(`${product.sku} is ready in Google Drive for 15 days.`);
      await new Promise((resolve) => window.setTimeout(resolve, 650));
      if (driveWindow && !driveWindow.closed) {
        driveWindow.location.replace(state.folder_url);
      } else {
        const opened = window.open(state.folder_url, "_blank", "noopener,noreferrer");
        if (!opened) setToast(`${product.sku} is ready. Please allow pop-ups to open Google Drive.`);
      }
    } catch (error) {
      if (driveWindow && !driveWindow.closed) driveWindow.close();
      setDriveJob(null);
      if (error instanceof SessionExpiredError) {
        setCurrentUser(null);
        window.location.hash = "";
        setActiveView("landing");
      }
      setToast(error instanceof Error ? error.message : "The Drive folder could not be created.");
    }
  };

  const navigate = (nextView: AppView) => {
    if (nextView === "admin" && !currentUser?.isAdmin) {
      setToast("Administrator access is required.");
      nextView = "catalogue";
    }
    if (nextView === "super-admin" && !currentUser?.isSuperAdmin) {
      setToast("Super administrator access is required.");
      nextView = currentUser?.isAdmin ? "admin" : "catalogue";
    }
    setActiveView(nextView);
    window.location.hash = nextView === "landing" ? "" : nextView;
    setFiltersOpen(false);
    setSearch("");
    setFavoriteOnly(false);
    setSelectedSku(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logoutCustomer();
      setCurrentUser(null);
      setProducts([]);
      setSelectedSku(null);
      setActiveView("landing");
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      setFiltersOpen(false);
      setSearch("");
      setFavoriteOnly(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
      setToast("You have signed out.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "We could not sign you out. Please try again.");
    } finally {
      setLoggingOut(false);
    }
  };

  const handleLoginSuccess = (user: AuthUser) => {
    const requestedView = viewFromHash();
    const destination = requestedView === "quotation" || requestedView === "orders" ? requestedView : "catalogue";
    setCurrentUser(user);
    setActiveView(destination);
    window.history.replaceState(null, "", `#${destination}`);
    setFiltersOpen(false);
    setSearch("");
    setFavoriteOnly(false);
    setSelectedSku(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (sessionLoading) {
    return <div className="app-boot" role="status"><SpinnerGap className="is-spinning" size={26} weight="bold" /><span>Checking your account…</span></div>;
  }

  return (
    <div className="app-shell">
      {activeView === "landing" || !currentUser ? (
        <LandingPage onLoginSuccess={handleLoginSuccess} />
      ) : (
        <>
          <Header
            activeView={activeView}
            onNavigate={navigate}
            onToggleFilters={() => setFiltersOpen(true)}
            onNotify={setToast}
            pendingNotificationCount={pendingNotificationCount}
            onLogout={handleLogout}
            loggingOut={loggingOut}
            user={currentUser}
          />

      {activeView === "catalogue" ? <>
      <div
        className={`workspace ${selectedProduct ? "has-drawer" : ""}`}
        style={{ "--filters-width": `${filterPanelWidth}px` } as CSSProperties}
      >
        <FilterSidebar
          products={products}
          themeOptions={themeOptions}
          filters={filters}
          open={filtersOpen}
          onChange={updateFilter}
          onReset={resetFilters}
          onClose={() => setFiltersOpen(false)}
        />

        <button
          type="button"
          className={resizingFilters ? "filter-resize-handle is-active" : "filter-resize-handle"}
          role="separator"
          aria-label="Resize asset filters"
          aria-orientation="vertical"
          aria-valuemin={FILTER_PANEL_MIN_WIDTH}
          aria-valuemax={FILTER_PANEL_MAX_WIDTH}
          aria-valuenow={filterPanelWidth}
          title="Drag to resize filters. Double-click to reset."
          onPointerDown={beginFilterResize}
          onKeyDown={resizeFiltersWithKeyboard}
          onDoubleClick={resetFilterPanelWidth}
        />

        {filtersOpen && <button className="page-scrim" onClick={() => setFiltersOpen(false)} aria-label="Close filters" />}

        <main className="catalogue" id="catalogue">
          <section className="catalogue-toolbar">
            <div>
              <strong>{visibleProducts.length} {visibleProducts.length === 1 ? "result" : "results"}</strong>
              <span>{parsedSearch.isBatchSkuSearch
                ? catalogueReady
                  ? `批量搜索 ${parsedSearch.skuOrder.length} 个 SKU · 找到 ${parsedSearch.skuOrder.length - batchMissingSkus.length} · 未找到 ${batchMissingSkus.length}`
                  : `批量搜索 ${parsedSearch.skuOrder.length} 个 SKU · 正在匹配完整素材库…`
                : favoriteOnly ? "Showing your saved products" : relatedSetCode ? `Exact SKU plus related products in ${relatedSetCode}` : search ? `Matching “${search}”` : ({ newest: "Sorted by most recently updated", name: "Sorted by product name", category: "Sorted by category", sku: "Sorted by SKU", assets: "Sorted by asset count" })[sort]}</span>
            </div>
            <ProductSearch value={search} onChange={setSearch} className="catalogue-search" />
            <div className="toolbar-actions">
              <button
                className={`favorites-filter ${favoriteOnly ? "is-active" : ""}`}
                onClick={() => setFavoriteOnly((value) => !value)}
                aria-pressed={favoriteOnly}
                title="Show only your favorites"
              >
                <Heart size={17} weight={favoriteOnly ? "fill" : "bold"} />
                Favorites
                <span>{favoriteCount}</span>
              </button>
              <label className="sort-control">
                <ArrowsDownUp size={17} weight="bold" />
                <select value={sort} onChange={(event) => setSort(event.target.value as SortMode)} aria-label="Sort products">
                  <option value="newest">Recently updated</option>
                  <option value="name">Name A–Z</option>
                  <option value="category">Category</option>
                  <option value="sku">SKU</option>
                  <option value="assets">Asset count</option>
                </select>
              </label>
              <div className="view-toggle" aria-label="View options">
                <button className={view === "grid" ? "is-active" : ""} onClick={() => changeView("grid")} aria-label="Card view" aria-pressed={view === "grid"}>
                  <GridFour size={18} weight="bold" />
                </button>
                <button className={view === "list" ? "is-active" : ""} onClick={() => changeView("list")} aria-label="List view" aria-pressed={view === "list"}>
                  <Rows size={18} weight="bold" />
                </button>
              </div>
            </div>
          </section>

          {parsedSearch.isBatchSkuSearch && catalogueReady && (
            <section className={`batch-search-summary ${batchMissingSkus.length ? "has-missing" : "is-complete"}`} aria-label="批量 SKU 搜索摘要">
              <div className="batch-search-counts">
                <span><small>搜索</small><strong>{parsedSearch.skuOrder.length}</strong></span>
                <span><small>找到</small><strong>{parsedSearch.skuOrder.length - batchMissingSkus.length}</strong></span>
                <span><small>未找到</small><strong>{batchMissingSkus.length}</strong></span>
              </div>
              {batchMissingSkus.length ? (
                <details>
                  <summary>查看未找到的 SKU</summary>
                  <div className="batch-missing-skus">
                    {batchMissingSkus.slice(0, 100).map((sku) => <code key={sku}>{sku}</code>)}
                    {batchMissingSkus.length > 100 && <span>另有 {batchMissingSkus.length - 100} 个，已一并发送</span>}
                  </div>
                </details>
              ) : <strong className="batch-search-complete">全部 SKU 均已找到</strong>}
              {batchMissingSkus.length > 0 && (
                <span className={`batch-notification-state is-${batchNotificationState}`}>
                  {batchNotificationState === "sending" ? "正在通知管理员…" : batchNotificationState === "sent" ? "未搜索到的已发送给管理员添加" : batchNotificationState === "error" ? "通知失败，请更改搜索后重试" : "准备通知管理员"}
                </span>
              )}
            </section>
          )}

          {loadError ? (
            <div className="empty-state">
              <Archive size={38} weight="duotone" />
              <strong>We could not load the asset library</strong>
              <p>{loadError}</p>
              <button className="button button-primary" onClick={() => setLibraryRefresh((value) => value + 1)}>Try again</button>
            </div>
          ) : loading ? (
            <div className="product-grid" aria-label="Loading assets">
              {Array.from({ length: 6 }).map((_, index) => <div className="skeleton-card" key={index} />)}
            </div>
          ) : visibleProducts.length ? (
            <div className={`product-grid ${view === "list" ? "is-list" : ""}`}>
              {displayedProducts.map((product, index) => (
                <Fragment key={product.sku}>
                  {index === relatedSetsStartIndex && exactSkuProduct && (
                    <div
                      className="related-sets-divider"
                      role="separator"
                      aria-label={`Related sets containing SKU ${exactSkuProduct.sku}`}
                    >
                      <span>Related sets containing SKU <strong>{exactSkuProduct.sku}</strong></span>
                    </div>
                  )}
                  <ProductCard
                    product={product}
                    selected={product.sku === selectedSku}
                    view={view}
                    onSelect={() => setSelectedSku(product.sku)}
                    onOpenDrive={() => openProductInDrive(product)}
                    onToggleFavorite={() => toggleProductFavorite(product)}
                  />
                </Fragment>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <Archive size={38} weight="duotone" />
              <strong>No matching assets found</strong>
              <p>Try a different keyword or reset your active filters.</p>
              <button className="button button-primary" onClick={() => { setSearch(""); resetFilters(); }}>Reset filters</button>
            </div>
          )}

          {!loading && !loadError && view === "list" && visibleProducts.length > LIST_PAGE_SIZE && (
            <nav className="catalogue-pagination" aria-label="Product list pagination">
              <span>
                Showing {pageStart + 1}–{Math.min(pageStart + LIST_PAGE_SIZE, visibleProducts.length)} of {visibleProducts.length}
              </span>
              <div className="pagination-pages">
                <button
                  type="button"
                  onClick={() => goToListPage(currentListPage - 1)}
                  disabled={currentListPage === 1}
                  aria-label="Previous page"
                >
                  <CaretLeft size={17} weight="bold" />
                </button>
                {listPageItems.map((item) => typeof item === "number" ? (
                  <button
                    type="button"
                    key={item}
                    className={item === currentListPage ? "is-active" : ""}
                    onClick={() => goToListPage(item)}
                    aria-current={item === currentListPage ? "page" : undefined}
                    aria-label={`Page ${item}`}
                  >
                    {item}
                  </button>
                ) : (
                  <span className="pagination-ellipsis" key={item} aria-hidden="true">…</span>
                ))}
                <button
                  type="button"
                  onClick={() => goToListPage(currentListPage + 1)}
                  disabled={currentListPage === listPageCount}
                  aria-label="Next page"
                >
                  <CaretRight size={17} weight="bold" />
                </button>
              </div>
            </nav>
          )}
        </main>

        {selectedProduct && (
          <ProductDrawer
            product={selectedProduct}
            onClose={() => setSelectedSku(null)}
            onOpenDrive={() => openProductInDrive(selectedProduct)}
            onToggleFavorite={() => toggleProductFavorite(selectedProduct)}
            isAdmin={currentUser.isAdmin}
            themeOptions={themeOptions}
            onSetCover={(asset) => updateProductCover(selectedProduct, asset)}
            onSetThemes={(themes) => updateProductThemes(selectedProduct, themes)}
            onNotify={setToast}
          />
        )}
      </div>

      {driveJob && (
        <div className={`drive-progress ${driveJob.complete ? "is-complete" : ""}`} role="status">
          {driveJob.complete ? <CheckCircle size={21} weight="fill" /> : <SpinnerGap size={21} weight="bold" />}
          <div>
            <strong>{driveJob.complete ? "Your Drive folder is ready" : `Preparing ${driveJob.sku}`}</strong>
            <span>{driveJob.complete ? "Available for 15 days" : `${driveJob.progress}% · Copying in Drive`}</span>
          </div>
          <div className="drive-meter"><span style={{ width: `${driveJob.progress}%` }} /></div>
          <button onClick={() => setDriveJob(null)} aria-label="Close progress"><X size={16} weight="bold" /></button>
        </div>
      )}
      </> : activeView === "quotation" ? (
        <CatalogSheet key={`${currentUser.id}:${currentUser.email}`} products={orderedCatalogProducts} search={search} onSearchChange={setSearch}
          draft={quotation.draft} publishedCatalogDraft={catalogOrder.draft} loading={loading} loadError={loadError} storageFailed={quotation.storageFailed}
          onRetry={() => setLibraryRefresh((v) => v + 1)} onUpdate={quotation.update}
          onUndo={quotation.undo} onRedo={quotation.redo} canUndo={quotation.canUndo} canRedo={quotation.canRedo}
          onToggle={toggleQuote} onEdit={editQuote} onNotify={setToast} onOpenDrive={openProductInDrive} onSetCover={updateProductCover}
          catalogOrderOwner={catalogOrder.ownerName} canManageCatalogOrder={catalogOrder.canManage}
          catalogOrderLoading={catalogOrder.loading} catalogOrderSaving={catalogOrder.saving} catalogOrderError={catalogOrder.error}
          onSaveCatalogOrder={catalogOrder.save} onSaveCatalogOrderOnly={catalogOrder.saveOrder} />
      ) : activeView === "orders" ? (
        <OrdersPanel user={currentUser} onNotify={setToast} onContinueShopping={() => navigate("quotation")}
          onReorder={(order) => {
            quotation.update((draft) => ({
              ...draft,
              title: order.title || draft.title,
              reference: order.reference,
              order: order.items.map((item) => item.sku),
              lines: {
                ...draft.lines,
                ...Object.fromEntries(order.items.map((item) => [item.sku, {
                  ...(draft.lines[item.sku] || emptyLine()),
                  quantity: String(item.quantity),
                }])),
              },
            }));
            setToast(`${order.productCount} products added to a new order.`);
            navigate("quotation");
          }} />
      ) : activeView === "admin" ? (
        <AdminPanel user={currentUser} search={search} onNotify={setToast} customerOnly />
      ) : (
        <SuperAdminPanel user={currentUser} onNotify={setToast} />
      )}
        </>
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
