import { useEffect, useMemo, useState } from "react";
import {
  CaretLeft,
  CaretRight,
  Check,
  Database,
  MagnifyingGlass,
  Plus,
  SpinnerGap,
  Tag,
  UsersThree,
  X,
} from "@phosphor-icons/react";
import { createAdminCategory, createAdminTheme, loadAdminProducts, updateAdminProductMetadata } from "./adminService";
import type { AdminProductPage } from "./types";

interface DataListPanelProps {
  search: string;
  onNotify: (message: string) => void;
}

const EMPTY_PAGE: AdminProductPage = {
  products: [],
  total: 0,
  page: 1,
  pageSize: 40,
  setCodes: [],
  categoryOptions: [],
  categoryTagOptions: [],
  themeOptions: [],
  source: "api",
};

export function DataListPanel({ search, onNotify }: DataListPanelProps) {
  const [query, setQuery] = useState(search);
  const [debouncedQuery, setDebouncedQuery] = useState(search.trim());
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AdminProductPage>(EMPTY_PAGE);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allResults, setAllResults] = useState(false);
  const [setCode, setSetCode] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [themes, setThemes] = useState<string[]>([]);
  const [saving, setSaving] = useState<"set" | "category" | "theme" | null>(null);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [newCategoryGroup, setNewCategoryGroup] = useState("Golf Headcover");
  const [newCategoryEn, setNewCategoryEn] = useState("");
  const [newCategoryZh, setNewCategoryZh] = useState("");
  const [addingCategory, setAddingCategory] = useState(false);
  const [showThemeModal, setShowThemeModal] = useState(false);
  const [newThemeLabel, setNewThemeLabel] = useState("");
  const [addingTheme, setAddingTheme] = useState(false);

  useEffect(() => setQuery(search), [search]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
      setSelected(new Set());
      setAllResults(false);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const refresh = async () => {
    setLoading(true);
    try {
      setData(await loadAdminProducts(debouncedQuery, page));
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "产品数据加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh().catch(() => undefined); }, [debouncedQuery, page]);

  const pageSkus = data.products.map((product) => product.sku);
  const pageSelected = Boolean(pageSkus.length) && pageSkus.every((sku) => selected.has(sku));
  const pageCount = Math.max(1, Math.ceil(data.total / data.pageSize));
  const targetCount = allResults ? data.total : selected.size;
  const targetLabel = allResults ? `当前搜索的 ${data.total} 条数据` : `已选 ${selected.size} 条数据`;
  const availableSetCodes = useMemo(() => [...new Set([...data.setCodes, setCode].filter(Boolean))], [data.setCodes, setCode]);
  const themeLabels = useMemo(
    () => Object.fromEntries(data.themeOptions.map((item) => [item.id, item.label])),
    [data.themeOptions],
  );

  const togglePage = () => {
    setAllResults(false);
    setSelected((current) => {
      const next = new Set(current);
      if (pageSelected) pageSkus.forEach((sku) => next.delete(sku));
      else pageSkus.forEach((sku) => next.add(sku));
      return next;
    });
  };

  const toggleSku = (sku: string) => {
    setAllResults(false);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(sku)) next.delete(sku); else next.add(sku);
      return next;
    });
  };

  const updateMetadata = async (field: "set" | "category" | "theme", clearSet = false) => {
    if (!targetCount) {
      onNotify("请先选择要修改的产品，或选择全部搜索结果");
      return;
    }
    if (allResults && !debouncedQuery) {
      onNotify("请先输入搜索条件，再选择全部搜索结果");
      return;
    }
    if (field === "set" && !clearSet && !setCode.trim()) {
      onNotify("请输入 Set00264 这样的套装编号");
      return;
    }
    if (field === "category" && !categoryId) {
      onNotify("请从固定分类词典中选择产品分类");
      return;
    }
    setSaving(field);
    try {
      await updateAdminProductMetadata({
        skus: [...selected],
        q: debouncedQuery,
        applyAll: allResults,
        setCode: clearSet ? "" : setCode,
        categoryId,
        themes,
        updateSet: field === "set",
        updateCategory: field === "category",
        updateThemes: field === "theme",
      });
      const category = data.categoryOptions.find((item) => item.id === categoryId);
      onNotify(`${targetLabel}已${
        field === "set"
          ? (clearSet ? "清除套装" : `设为 ${setCode}`)
          : field === "theme"
            ? (themes.length ? `设置主题为 ${themes.map((theme) => themeLabels[theme]).join("、")}` : "清除主题")
            : `确认分类为 ${category?.labelZh || categoryId}`
      }`);
      setSelected(new Set());
      setAllResults(false);
      await refresh();
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "批量修改失败");
    } finally {
      setSaving(null);
    }
  };

  const addCategory = async () => {
    if (!newCategoryEn.trim()) {
      onNotify("请输入英文分类名称");
      return;
    }
    setAddingCategory(true);
    try {
      const created = await createAdminCategory({
        group: newCategoryGroup,
        labelEn: newCategoryEn.trim(),
        labelZh: newCategoryZh.trim(),
      });
      setCategoryId(created.id);
      setShowCategoryModal(false);
      setNewCategoryEn("");
      setNewCategoryZh("");
      await refresh();
      onNotify(`已新增分类 ${created.labelEn}`);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "新增分类失败");
    } finally {
      setAddingCategory(false);
    }
  };

  const addTheme = async () => {
    if (!newThemeLabel.trim()) {
      onNotify("请输入英文主题名称");
      return;
    }
    setAddingTheme(true);
    try {
      const created = await createAdminTheme(newThemeLabel.trim());
      setThemes((current) => [...new Set([...current, created.id])]);
      setShowThemeModal(false);
      setNewThemeLabel("");
      await refresh();
      onNotify(`已新增主题 ${created.label}`);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "新增主题失败");
    } finally {
      setAddingTheme(false);
    }
  };

  return (
    <section className="admin-section data-list-section">
      <header className="admin-page-heading">
        <div><span className="eyebrow">Product metadata</span><h1>数据列表</h1><p>按 SKU、品名或品牌查找产品，批量确认固定分类、主题和同一套装。</p></div>
        <div className="data-list-total"><Database size={20} weight="duotone" /><span><strong>{data.total}</strong><small>匹配数据</small></span></div>
      </header>

      <section className="data-list-tools">
        <label className="admin-search-field data-list-search"><MagnifyingGlass size={18} weight="bold" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 SKU、英文品名、品牌、主题或套装" /></label>
        <div className="data-list-scope">
          <strong>{targetLabel}</strong>
          {debouncedQuery && data.total > 0 && <button type="button" className={allResults ? "is-active" : ""} onClick={() => { setAllResults((value) => !value); setSelected(new Set()); }}><UsersThree size={16} weight="bold" />{allResults ? "已选择全部结果" : `选择全部 ${data.total} 条结果`}</button>}
        </div>
        <div className="data-list-bulk-fields">
          <div className="data-list-category-control">
            <label><span>产品分类</span><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">请选择分类</option>{[...new Set(data.categoryOptions.map((item) => item.group))].map((group) => <optgroup label={group} key={group}>{data.categoryOptions.filter((item) => item.group === group).map((option) => <option value={option.id} key={option.id}>{option.labelZh ? `${option.labelZh} / ` : ""}{option.labelEn}</option>)}</optgroup>)}</select></label>
            <button type="button" className="data-list-add-category" onClick={() => setShowCategoryModal(true)}><Plus size={15} weight="bold" />新增分类</button>
          </div>
          <button type="button" onClick={() => updateMetadata("category")} disabled={Boolean(saving)}>{saving === "category" ? <SpinnerGap className="is-spinning" size={16} /> : <Check size={16} weight="bold" />}确认分类</button>
          <label><span>统一套装</span><input value={setCode} onChange={(event) => setSetCode(event.target.value)} placeholder="Set00264" list="admin-set-codes" /><datalist id="admin-set-codes">{availableSetCodes.map((code) => <option value={code} key={code} />)}</datalist></label>
          <button type="button" onClick={() => updateMetadata("set")} disabled={Boolean(saving)}>{saving === "set" ? <SpinnerGap className="is-spinning" size={16} /> : <UsersThree size={16} weight="bold" />}设置套装</button>
          <button type="button" className="is-muted" onClick={() => updateMetadata("set", true)} disabled={Boolean(saving)}>清除套装</button>
          <div className="data-list-theme-editor">
            <div className="data-list-theme-heading">
              <span>主题 Theme（可多选）</span>
              <small>由管理员维护；不受 Drive 同步影响。未选择后应用即清空。</small>
              <button type="button" className="data-list-add-theme" onClick={() => setShowThemeModal(true)}>
                <Plus size={14} weight="bold" />新增主题
              </button>
            </div>
            <div className="data-list-theme-options">
              {data.themeOptions.map((option) => {
                const checked = themes.includes(option.id);
                return (
                  <label className={checked ? "data-theme-option is-selected" : "data-theme-option"} key={option.id}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => setThemes((current) => current.includes(option.id)
                        ? current.filter((theme) => theme !== option.id)
                        : [...current, option.id])}
                    />
                    <span>{checked && <Check size={11} weight="bold" />}</span>
                    {option.label}
                  </label>
                );
              })}
            </div>
            <button type="button" onClick={() => updateMetadata("theme")} disabled={Boolean(saving)}>
              {saving === "theme" ? <SpinnerGap className="is-spinning" size={16} /> : <Tag size={16} weight="fill" />}
              应用主题
            </button>
          </div>
        </div>
      </section>

      <section className="data-list-card">
        <div className="data-list-table-wrap">
          <table className="data-list-table">
            <thead><tr><th><label className="admin-check"><input type="checkbox" checked={pageSelected} onChange={togglePage} aria-label="选择本页" /><span><Check size={13} weight="bold" /></span></label></th><th>SKU / 品名</th><th>品牌与固定分类</th><th>主题</th><th>套装</th><th>素材</th></tr></thead>
            <tbody>
              {data.products.map((product) => (
                <tr key={product.sku} className={selected.has(product.sku) ? "is-selected" : ""}>
                  <td><label className="admin-check"><input type="checkbox" checked={selected.has(product.sku)} onChange={() => toggleSku(product.sku)} aria-label={`选择 ${product.sku}`} /><span><Check size={13} weight="bold" /></span></label></td>
                  <td><strong>{product.sku}</strong><span>{product.englishName || "English name not set"}</span>{product.chineseName && <small>{product.chineseName}</small>}</td>
                  <td><strong>{product.brand || "—"}</strong><small>{product.categoryZh ? `${product.categoryZh} / ${product.category}` : product.category || "—"}</small><span className={`category-review-chip ${product.categoryStatus}`}>{product.categoryStatus === "verified" ? "已确认" : product.categoryStatus === "needs_review" ? "待复核" : "未分类"}</span></td>
                  <td>{product.themes.length ? <div className="data-theme-list">{product.themes.map((theme) => <span className="data-theme-chip" key={theme}>{themeLabels[theme] || theme}</span>)}</div> : <span className="data-empty-value">未设置</span>}</td>
                  <td>{product.setCode ? <span className="data-set-chip">{product.setCode}</span> : <span className="data-empty-value">未设置</span>}</td>
                  <td><strong>{product.fileCount}</strong><small> files</small></td>
                </tr>
              ))}
            </tbody>
          </table>
          {loading && <div className="data-list-loading"><SpinnerGap className="is-spinning" size={22} weight="bold" /> 正在加载产品数据…</div>}
          {!loading && !data.products.length && <div className="admin-empty"><Database size={34} weight="duotone" /><strong>没有匹配的数据</strong><span>请调整 SKU 或品名关键词。</span></div>}
        </div>
        <footer className="data-list-pagination"><span>第 {page} / {pageCount} 页 · 每页 {data.pageSize} 条</span><div><button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}><CaretLeft size={16} weight="bold" />上一页</button><button type="button" onClick={() => setPage((value) => Math.min(pageCount, value + 1))} disabled={page >= pageCount}>下一页<CaretRight size={16} weight="bold" /></button></div></footer>
      </section>

      {showCategoryModal && (
        <div className="review-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCategoryModal(false); }}>
          <section className="permission-modal category-create-modal" role="dialog" aria-modal="true" aria-labelledby="category-create-title">
            <header className="review-modal-heading">
              <div><span>Product taxonomy</span><h2 id="category-create-title">新增产品分类</h2><small>新分类会加入统一分类字典，并出现在管理员的全部分类选择器中。</small></div>
              <button type="button" onClick={() => setShowCategoryModal(false)} aria-label="关闭新增分类弹窗"><X size={20} weight="bold" /></button>
            </header>
            <div className="permission-modal-body">
              <div className="permission-modal-form admin-form">
                <label><span>所属分类组</span><select value={newCategoryGroup} onChange={(event) => setNewCategoryGroup(event.target.value)}><option value="Golf Headcover">Golf Headcover</option><option value="Golf Accessories">Golf Accessories</option></select></label>
                <label><span>英文分类名称</span><input value={newCategoryEn} onChange={(event) => setNewCategoryEn(event.target.value)} placeholder="e.g. Junior Covers" autoFocus /></label>
                <label><span>中文名称（可选）</span><input value={newCategoryZh} onChange={(event) => setNewCategoryZh(event.target.value)} placeholder="便于管理员识别" /></label>
                <p className="permission-field-help">新增后可立即给产品批量分类；客户端只会展示实际有产品的分类。</p>
              </div>
            </div>
            <footer className="permission-modal-actions"><button className="button button-secondary" type="button" onClick={() => setShowCategoryModal(false)}>取消</button><button className="button button-primary" type="button" onClick={addCategory} disabled={addingCategory || !newCategoryEn.trim()}>{addingCategory ? <SpinnerGap className="is-spinning" size={16} /> : <Plus size={16} weight="bold" />}新增分类</button></footer>
          </section>
        </div>
      )}

      {showThemeModal && (
        <div className="review-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowThemeModal(false); }}>
          <section className="permission-modal category-create-modal" role="dialog" aria-modal="true" aria-labelledby="theme-create-title">
            <header className="review-modal-heading">
              <div><span>Theme taxonomy</span><h2 id="theme-create-title">新增主题</h2><small>新增主题会出现在客户筛选、素材详情和后台批量设置中。</small></div>
              <button type="button" onClick={() => setShowThemeModal(false)} aria-label="关闭新增主题弹窗"><X size={20} weight="bold" /></button>
            </header>
            <div className="permission-modal-body">
              <div className="permission-modal-form admin-form">
                <label><span>英文主题名称</span><input value={newThemeLabel} onChange={(event) => setNewThemeLabel(event.target.value)} placeholder="e.g. Summer Campaign" autoFocus /></label>
                <p className="permission-field-help">主题词典由管理员维护；创建后不会被 Google Drive 同步覆盖。</p>
              </div>
            </div>
            <footer className="permission-modal-actions"><button className="button button-secondary" type="button" onClick={() => setShowThemeModal(false)}>取消</button><button className="button button-primary" type="button" onClick={addTheme} disabled={addingTheme || !newThemeLabel.trim()}>{addingTheme ? <SpinnerGap className="is-spinning" size={16} /> : <Plus size={16} weight="bold" />}新增主题</button></footer>
          </section>
        </div>
      )}
    </section>
  );
}
