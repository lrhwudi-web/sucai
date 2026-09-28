import { lazy, Suspense, useState } from "react";
import type { CatalogSheetProps } from "./WorkbookSheet";

const CustomerCatalog = lazy(() => import("./CustomerCatalog").then(module => ({ default: module.CustomerCatalog })));
const WorkbookCatalogSheet = lazy(() => import("./WorkbookSheet").then(module => ({ default: module.WorkbookCatalogSheet })));

export function CatalogSheet(props: CatalogSheetProps) {
  const [customerView, setCustomerView] = useState<"catalog" | "workbook">("catalog");
  return <Suspense fallback={<div className="app-boot" role="status">Opening product catalog…</div>}>
    {!props.canManageCatalogOrder && customerView === "catalog"
      ? <CustomerCatalog {...props} onShowWorkbook={() => setCustomerView("workbook")} />
      : <WorkbookCatalogSheet {...props} onShowCards={props.canManageCatalogOrder ? undefined : () => setCustomerView("catalog")} />}
  </Suspense>;
}
