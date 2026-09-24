import { useMemo, useState } from "react";
import {
  BookOpen,
  CalendarBlank,
  CaretDown,
  CaretRight,
  Check,
  Folder,
  FunnelSimple,
  Images,
  Package,
  PaintBrushBroad,
  PlayCircle,
  Storefront,
  Tag,
  UsersThree,
  X,
} from "@phosphor-icons/react";
import type { MaterialProduct, ProductFilters, ThemeOption } from "../types";
import { PRODUCT_CATEGORY_GROUPS } from "../utils/category";

interface FilterSidebarProps {
  products: MaterialProduct[];
  themeOptions: ThemeOption[];
  filters: ProductFilters;
  open: boolean;
  onChange: (key: keyof ProductFilters, value: string | string[]) => void;
  onReset: () => void;
  onClose: () => void;
}

const fieldOptions = (
  products: MaterialProduct[],
  getter: (product: MaterialProduct) => string,
) => [...new Set(products.map(getter))].sort((a, b) => a.localeCompare(b));

const assignedOptions = (options: string[]) => options.filter(
  (option) => option.trim() && option.trim().toLowerCase() !== "unassigned",
);

const prioritizeBrandOptions = (options: string[]) => [...options].sort((a, b) => {
  const aIsCraftsmanGolf = a.trim().toLowerCase() === "craftsman golf";
  const bIsCraftsmanGolf = b.trim().toLowerCase() === "craftsman golf";
  if (aIsCraftsmanGolf !== bIsCraftsmanGolf) return aIsCraftsmanGolf ? -1 : 1;
  return a.localeCompare(b);
});

const OTHER_OPTIONS = [
  { label: "Product Catalogs", Icon: BookOpen },
  { label: "Brand Assets", Icon: PaintBrushBroad },
  { label: "Packaging Assets", Icon: Package },
  { label: "Show & Exhibitions", Icon: Storefront },
  { label: "Event & Sponsorships", Icon: CalendarBlank },
  { label: "Influencer Assets", Icon: UsersThree },
  { label: "Collection Assets", Icon: Folder },
];

const ASSET_TYPE_OPTIONS = ["image", "video", "kol_ugc"];
const ASSET_TYPE_LABELS: Record<string, string> = {
  image: "Image",
  video: "Video",
  kol_ugc: "KOL & UGC",
};
const ASSET_TYPE_ICONS = {
  image: Images,
  video: PlayCircle,
  kol_ugc: UsersThree,
};

function FlowStep({
  number,
  title,
  children,
  last = false,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
  last?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const Icon = number === 1 ? Tag : number === 2 ? Package : Images;
  return (
    <section className={last ? "filter-flow-step is-last" : "filter-flow-step"}>
      <div className="filter-flow-marker" aria-hidden="true">
        <span>{number}</span>
      </div>
      <div className="filter-flow-content">
        <button
          type="button"
          className="filter-flow-toggle"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          <span><Icon size={15} weight="regular" /> {title}</span>
          <CaretDown className={expanded ? "is-open" : ""} size={13} weight="bold" />
        </button>
        {expanded && children}
      </div>
    </section>
  );
}

function BrandStep({
  selected,
  options,
  onChange,
}: {
  selected: string[];
  options: string[];
  onChange: (brands: string[]) => void;
}) {
  const toggleBrand = (brand: string) => {
    onChange(
      selected.includes(brand)
        ? selected.filter((item) => item !== brand)
        : [...selected, brand],
    );
  };

  return (
    <div className="brand-filter-options" role="group" aria-label="Brand options">
      <button
        type="button"
        className={!selected.length ? "filter-choice is-selected" : "filter-choice"}
        onClick={() => onChange([])}
        aria-pressed={!selected.length}
      >
        <span>All brands</span>
        {!selected.length && <Check size={15} weight="bold" />}
      </button>
      {options.map((option) => {
        const checked = selected.includes(option);
        return (
          <div className={checked ? "category-check brand-check is-selected" : "category-check brand-check"} key={option}>
            <label className="multi-choice-toggle" title={`Add or remove ${option} from the Brand selection`}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleBrand(option)}
                aria-label={`Include ${option} in Brand selection`}
              />
              <span className="category-check-box">{checked && <Check size={11} weight="bold" />}</span>
            </label>
            <button
              type="button"
              className="multi-choice-text"
              onClick={() => onChange([option])}
              aria-pressed={checked && selected.length === 1}
              title={`Show only ${option}`}
            >
              {option}
            </button>
          </div>
        );
      })}
    </div>
  );
}

function ProductCategoryFilter({
  selected,
  available,
  groupByCategory,
  onChange,
}: {
  selected: string[];
  available: string[];
  groupByCategory: Record<string, string>;
  onChange: (categories: string[]) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["Golf Headcover"]));
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [showAllGroups, setShowAllGroups] = useState(false);
  const availableSet = useMemo(() => new Set(available), [available]);
  const builtIn = useMemo(
    () => new Set<string>(PRODUCT_CATEGORY_GROUPS.flatMap((group) => [...group.categories])),
    [],
  );
  const groups = PRODUCT_CATEGORY_GROUPS.map((group) => ({
    label: group.label,
    categories: [
      ...group.categories.filter((category) => availableSet.has(category)),
      ...available.filter(
        (category) => !builtIn.has(category) && groupByCategory[category] === group.label,
      ),
    ],
  })).filter((group) => group.categories.length);
  const visibleGroups = showAllGroups ? groups : groups.slice(0, 1);

  const toggleExpanded = (group: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const toggleCategory = (category: string) => {
    onChange(
      selected.includes(category)
        ? selected.filter((item) => item !== category)
        : [...selected, category],
    );
  };

  return (
    <div className="category-filter">
      <button
        type="button"
        className={!selected.length ? "filter-choice is-selected" : "filter-choice"}
        onClick={() => onChange([])}
        aria-pressed={!selected.length}
      >
        <span>All categories</span>
        {!selected.length && <Check size={15} weight="bold" />}
      </button>
      {visibleGroups.map((group, groupIndex) => {
        const isExpanded = expanded.has(group.label);
        const showsAllCategories = expandedCategories.has(group.label);
        const visibleCategories = showsAllCategories ? group.categories : group.categories.slice(0, 10);
        const selectedCount = group.categories.filter((category) => selected.includes(category)).length;
        return (
          <section className="category-filter-section" key={group.label}>
            <button
              type="button"
              className="category-filter-heading"
              onClick={() => toggleExpanded(group.label)}
              aria-expanded={isExpanded}
            >
              {isExpanded ? <CaretDown size={15} weight="bold" /> : <CaretRight size={15} weight="bold" />}
              <span>{group.label}</span>
              {selectedCount > 0 && <em>{selectedCount}</em>}
            </button>
            {isExpanded && (
              <div className="category-filter-options">
                {visibleCategories.map((category) => {
                  const checked = selected.includes(category);
                  return (
                    <div className={checked ? "category-check is-selected" : "category-check"} key={category}>
                      <label className="multi-choice-toggle" title={`Add or remove ${category} from the category selection`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleCategory(category)}
                          aria-label={`Include ${category} in Product Category selection`}
                        />
                        <span className="category-check-box">{checked && <Check size={11} weight="bold" />}</span>
                      </label>
                      <button
                        type="button"
                        className="multi-choice-text"
                        onClick={() => onChange([category])}
                        aria-pressed={checked && selected.length === 1}
                        title={`Show only ${category}`}
                      >
                        {category}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
            {isExpanded && groupIndex === 0 && (group.categories.length > 10 || groups.length > 1) && (
              <button
                type="button"
                className="filter-show-more category-show-more"
                onClick={() => setExpandedCategories((current) => {
                  const next = new Set(current);
                  const willShowAll = !next.has(group.label);
                  if (willShowAll) next.add(group.label);
                  else next.delete(group.label);
                  setShowAllGroups(willShowAll);
                  return next;
                })}
              >
                {showsAllCategories ? "Show less" : "Show more"}
                <CaretDown className={showsAllCategories ? "is-rotated" : ""} size={13} weight="bold" />
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}

function AssetTypeStep({
  value,
  options,
  onSelect,
}: {
  value: string;
  options: string[];
  onSelect: (value: string) => void;
}) {
  return (
    <div className="asset-type-segments" role="group" aria-label="Asset type options">
      {ASSET_TYPE_OPTIONS.map((option) => {
        const Icon = ASSET_TYPE_ICONS[option as keyof typeof ASSET_TYPE_ICONS];
        const selected = value === option;
        const available = options.includes(option);
        return (
          <button
            type="button"
            key={option}
            className={selected ? "is-selected" : ""}
            onClick={() => onSelect(selected ? "" : option)}
            aria-pressed={selected}
            disabled={!available}
          >
            <Icon size={18} weight={selected ? "fill" : "regular"} />
            <span>{ASSET_TYPE_LABELS[option] || option}</span>
          </button>
        );
      })}
    </div>
  );
}

function ThemeRefinement({
  selected,
  options,
  onChange,
}: {
  selected: string[];
  options: string[];
  onChange: (themes: string[]) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? options : options.slice(0, 2);
  const toggleTheme = (theme: string) => {
    onChange(
      selected.includes(theme)
        ? selected.filter((item) => item !== theme)
        : [...selected, theme],
    );
  };
  return (
    <section className="theme-refinement">
      <div className="theme-refinement-heading">
        <span><Tag size={15} weight="fill" /> Theme</span>
        <small>Product refinement</small>
      </div>
      <div className="theme-chip-list">
        <button
          type="button"
          className={!selected.length ? "theme-chip is-selected" : "theme-chip"}
          onClick={() => onChange([])}
          aria-pressed={!selected.length}
        >
          All themes
          {!selected.length && <Check size={11} weight="bold" />}
        </button>
        {visible.map((theme) => {
          const checked = selected.includes(theme);
          return (
            <button
              type="button"
              key={theme}
              className={checked ? "theme-chip is-selected" : "theme-chip"}
              onClick={() => toggleTheme(theme)}
              aria-pressed={checked}
            >
              {theme}
              {checked && <Check size={11} weight="bold" />}
            </button>
          );
        })}
        {options.length > 2 && (
          <button type="button" className="theme-chip theme-chip-more" onClick={() => setShowAll((value) => !value)}>
            {showAll ? "Less" : `+${options.length - 2} more`}
          </button>
        )}
      </div>
    </section>
  );
}

function OtherCollections({
  selected,
  available,
  onChange,
}: {
  selected: string[];
  available: string[];
  onChange: (categories: string[]) => void;
}) {
  const toggleCategory = (category: string) => {
    onChange(selected.includes(category) ? [] : [category]);
  };
  return (
    <section className="other-collections" aria-labelledby="other-collections-title">
      <div className="other-collections-heading">
        <span className="filter-section-kicker" id="other-collections-title">Other collections</span>
        <span className="independent-badge">Independent</span>
      </div>
      <p>Clicking a collection resets the product filters above</p>
      <div className="other-collection-list">
        {OTHER_OPTIONS.map(({ label, Icon }) => {
          const checked = selected.includes(label);
          const isAvailable = available.includes(label);
          return (
            <button
              type="button"
              key={label}
              className={checked ? "other-collection-row is-selected" : "other-collection-row"}
              onClick={() => toggleCategory(label)}
              aria-pressed={checked}
              title={isAvailable ? undefined : "No indexed packages yet"}
            >
              <span className="other-collection-icon"><Icon size={17} weight={checked ? "fill" : "regular"} /></span>
              <span>{label}</span>
              {checked ? <Check size={14} weight="bold" /> : <CaretRight size={14} weight="bold" />}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function FilterSidebar({ products, themeOptions, filters, open, onChange, onReset, onClose }: FilterSidebarProps) {
  const activeCount = Number(Boolean(filters.brand.length))
    + Number(Boolean(filters.category.length))
    + Number(Boolean(filters.theme.length))
    + Number(Boolean(filters.other.length))
    + Number(Boolean(filters.material))
    + Number(Boolean(filters.assetKind))
    + Number(Boolean(filters.permission));
  const productAssets = products.filter((product) => !product.otherCategory);
  const categoryProducts = filters.brand.length
    ? productAssets.filter((product) => filters.brand.includes(product.brand))
    : productAssets;
  const assetTypeProducts = filters.category.length
    ? categoryProducts.filter((product) => filters.category.includes(product.category))
    : categoryProducts;
  const assetTypeOptions = ASSET_TYPE_OPTIONS.filter((option) => (
    assetTypeProducts.some((product) => (product.assetTypes || []).includes(option))
  ));
  const groupByCategory = Object.fromEntries(
    categoryProducts.map((product) => [product.category, product.categoryGroup || ""]),
  );
  const availableOther = [...new Set(products.map((product) => product.otherCategory).filter(Boolean))];
  const availableThemes = themeOptions
    .map((theme) => theme.label)
    .filter((theme) => assetTypeProducts.some((product) => product.themes.includes(theme)));

  return (
    <aside className={open ? "filters-panel is-open" : "filters-panel"} aria-label="Asset filters">
      <div className="filters-heading">
        <div>
          <span className="eyebrow"><FunnelSimple size={14} weight="fill" /> Asset filters</span>
          <strong>Narrow your results</strong>
        </div>
        <button className="icon-button close-filters" onClick={onClose} aria-label="Close filters">
          <X size={18} weight="bold" />
        </button>
      </div>

      <div className="filter-scroll">
        <section className="product-attribute-filter" aria-labelledby="product-attributes-title">
          <span className="filter-section-kicker" id="product-attributes-title">Product attributes</span>
          <div className="filter-flow">
            <FlowStep number={1} title="Brand">
              <BrandStep
                selected={filters.brand}
                options={prioritizeBrandOptions(assignedOptions(fieldOptions(productAssets, (product) => product.brand)))}
                onChange={(value) => onChange("brand", value)}
              />
            </FlowStep>
            <FlowStep number={2} title="Product Category">
              <ProductCategoryFilter
                selected={filters.category}
                available={assignedOptions(fieldOptions(categoryProducts, (product) => product.category))}
                groupByCategory={groupByCategory}
                onChange={(value) => onChange("category", value)}
              />
            </FlowStep>
            <FlowStep number={3} title="Asset Type" last>
              <AssetTypeStep
                value={filters.assetKind}
                options={assetTypeOptions.length ? assetTypeOptions : ASSET_TYPE_OPTIONS}
                onSelect={(value) => onChange("assetKind", value)}
              />
            </FlowStep>
          </div>
          <ThemeRefinement
            selected={filters.theme}
            options={availableThemes.length ? availableThemes : themeOptions.map((theme) => theme.label)}
            onChange={(value) => onChange("theme", value)}
          />
        </section>
        <OtherCollections
          selected={filters.other}
          available={availableOther}
          onChange={(value) => onChange("other", value)}
        />
      </div>

      <div className="filters-footer">
        <button className="button button-quiet" onClick={onReset} disabled={!activeCount}>Reset filters</button>
        <span>{products.length} product packages</span>
      </div>
    </aside>
  );
}
