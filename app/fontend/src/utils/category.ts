const CATEGORY_ORDER_PREFIX = /^\s*\d{1,3}(?:\s*[-_.]\s*|\s+)/;

export const PRODUCT_CATEGORY_GROUPS = [
  {
    label: "Golf Headcover",
    categories: [
      "Plush Covers",
      "Driver Covers",
      "Fairway Covers",
      "Hybrid Covers",
      "Blade Putter Covers",
      "Mallet Putter Covers",
      "Mid-Mallet Putter Covers",
      "Square Mallet Putter Covers",
      "Iron Cover Sets",
      "Wedge Cover Sets",
      "Alignment Stick Covers",
    ],
  },
  {
    label: "Golf Accessories",
    categories: [
      "Divot Tools & Ball Markers",
      "Scorecard Holders",
      "Golf Towels",
      "Golf Ball & Tee Pouchs",
      "Valuables Pouches",
      "Glove Caddie",
      "Rangefinder Case",
      "Others",
    ],
  },
] as const;

const CATEGORY_ALIASES = new Map<string, string>([
  ["plush headcover", "Plush Covers"],
  ["plush headcovers", "Plush Covers"],
  ["plush cover", "Plush Covers"],
  ["plush covers", "Plush Covers"],
  ["动物帽套", "Plush Covers"],
  ["毛绒杆套", "Plush Covers"],
  ["driver cover", "Driver Covers"],
  ["driver covers", "Driver Covers"],
  ["fairway cover", "Fairway Covers"],
  ["fairway covers", "Fairway Covers"],
  ["hybrid cover", "Hybrid Covers"],
  ["hybrid covers", "Hybrid Covers"],
  ["blade putter cover", "Blade Putter Covers"],
  ["blade putter covers", "Blade Putter Covers"],
  ["mallet putter cover", "Mallet Putter Covers"],
  ["mallet putter covers", "Mallet Putter Covers"],
  ["mid mallet putter cover", "Mid-Mallet Putter Covers"],
  ["mid mallet putter covers", "Mid-Mallet Putter Covers"],
  ["square mallet putter cover", "Square Mallet Putter Covers"],
  ["square mallet putter covers", "Square Mallet Putter Covers"],
  ["iron cover", "Iron Cover Sets"],
  ["iron covers", "Iron Cover Sets"],
  ["iron cover set", "Iron Cover Sets"],
  ["iron cover sets", "Iron Cover Sets"],
  ["wedge cover", "Wedge Cover Sets"],
  ["wedge covers", "Wedge Cover Sets"],
  ["wedge cover set", "Wedge Cover Sets"],
  ["wedge cover sets", "Wedge Cover Sets"],
  ["alignment stick cover", "Alignment Stick Covers"],
  ["alignment stick covers", "Alignment Stick Covers"],
  ["divot tool ball marker", "Divot Tools & Ball Markers"],
  ["divot tools ball markers", "Divot Tools & Ball Markers"],
  ["scorebook", "Scorecard Holders"],
  ["scorecard holder", "Scorecard Holders"],
  ["scorecard holders", "Scorecard Holders"],
  ["golf towel", "Golf Towels"],
  ["golf towels", "Golf Towels"],
  ["golf ball tee pouch", "Golf Ball & Tee Pouchs"],
  ["golf ball tee pouchs", "Golf Ball & Tee Pouchs"],
  ["golf valuables pouch", "Valuables Pouches"],
  ["valuables pouch", "Valuables Pouches"],
  ["valuables pouches", "Valuables Pouches"],
  ["golf glove case", "Glove Caddie"],
  ["glove caddie", "Glove Caddie"],
  ["rangefinder cases", "Rangefinder Case"],
  ["rangefinder case", "Rangefinder Case"],
  ["other golf accessory", "Others"],
  ["others", "Others"],
  ["headcover set", "Others"],
  ["headcover sets", "Others"],
  ["headcovers set", "Others"],
  ["product packaging", "Others"],
  ["big crazy 包装系列", "Others"],
]);

function stripOrderingPrefix(value?: string): string {
  return (value || "")
    .replace(CATEGORY_ORDER_PREFIX, "")
    .replace(/\s+/g, " ")
    .trim();
}

function comparisonKey(value?: string): string {
  return stripOrderingPrefix(value)
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, " ")
    .trim();
}

export function normalizeCategoryLabel(value?: string): string {
  const label = stripOrderingPrefix(value);
  if (!label) return "Unassigned";
  return CATEGORY_ALIASES.get(comparisonKey(label)) || label;
}

export function normalizeBrandLabel(value?: string): string {
  const label = stripOrderingPrefix(value);
  if (!label) return "Unassigned";
  return isNoBrandLabel(label) ? "No Brand" : label;
}

export function isNoBrandLabel(value?: string): boolean {
  return ["no brand", "nobrand", "unbranded", "无牌"].includes(comparisonKey(value));
}

export function normalizeProductTaxonomy(brand?: string, category?: string, material?: string) {
  const noBrand = isNoBrandLabel(brand) || isNoBrandLabel(material);
  return {
    brand: noBrand ? "No Brand" : normalizeBrandLabel(brand),
    category: normalizeCategoryLabel(category),
    material: isNoBrandLabel(material) ? "" : material || "",
  };
}
