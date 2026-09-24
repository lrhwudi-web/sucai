import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointer } from "react";
import { ArrowCounterClockwise, ArrowClockwise, Copy, ClipboardText, Trash, Columns, Snowflake, UploadSimple, Funnel, CaretDown, X, Table, FloppyDisk, ListBullets, DotsSixVertical, Database } from "@phosphor-icons/react";
import type { MaterialAsset, MaterialProduct } from "../types";
import type { QuoteDraft, QuoteLine, SheetLayout } from "./quotation";
import { isQuotable, quoteProducts, formatMoney } from "./quotation";
import { AssetImage } from "../components/AssetImage";
import { ProductSearch } from "../components/ProductSearch";
import { thumbnailVariantUrl } from "../utils/thumbnails";
import { QuoteBuilder } from "./QuoteBuilder";
import { COLUMNS, applyCellChanges, bounds, canEditCatalogColumn, columnLabel, columnsForCatalog, createCalculator, defaultCustomerLayout, fillChanges, fromTSV, layoutOf, rangeAddress, rawValue, sheetTotals, toTSV, type CellChange, type CellRange, type ColumnKey, type Point } from "./workbookData.ts";
import { columnLetter, parseAddress, shiftFormula } from "./formulas.ts";
import { ColumnFilterMenu } from "./ColumnFilterMenu";
import { filteredRecords, filterOptions, type ColumnFilters, type FilterRecord } from "./columnFilters.ts";
import { ProductImageGallery } from "./ProductImageGallery";
import { CustomerCatalog } from "./CustomerCatalog";
import { catalogDraftFingerprint, completeCatalogOrder, groupCatalogProducts, moveCatalogProduct, type CatalogGroupKey } from "./catalogOrder";
import { assertExcelImportSize } from "./excelImportPolicy";
import { reportMissingSkus } from "../services/materials";
import "./catalogSheet.css";

export interface CatalogSheetProps { products:MaterialProduct[]; search:string; onSearchChange:(value:string)=>void; draft:QuoteDraft; publishedCatalogDraft:QuoteDraft|null; loading:boolean; loadError:string; storageFailed:boolean; onRetry:()=>void; onUpdate:(fn:(d:QuoteDraft)=>QuoteDraft)=>void; onToggle:(skus:string[],selected:boolean)=>void; onEdit:(sku:string,p:Partial<QuoteLine>)=>void; onNotify:(s:string)=>void; onOpenDrive:(product:MaterialProduct)=>void; onSetCover:(product:MaterialProduct,asset:MaterialAsset)=>Promise<void>; onUndo:()=>void; onRedo:()=>void; canUndo:boolean; canRedo:boolean; catalogOrderOwner:string; canManageCatalogOrder:boolean; catalogOrderLoading:boolean; catalogOrderSaving:boolean; catalogOrderError:string; onSaveCatalogOrder:(skus:string[],draft:QuoteDraft)=>Promise<unknown>; onSaveCatalogOrderOnly:(skus:string[])=>Promise<unknown> }
type Props = CatalogSheetProps & { onShowCards?: () => void };
type Editor={sku:string;key:ColumnKey;row:number;text:string;mode:"cell"|"formula"};
type ImportSkuSummary={searched:number;matched:number;missingSkus:string[];duplicates:number;notificationState:"idle"|"sending"|"sent"|"error"};
const EMPTY_RANGE:CellRange={start:{r:0,c:0},end:{r:0,c:0}};
const GUTTER=42,HEADER=137;
function orderedProducts(records:FilterRecord<MaterialProduct>[],filters:ColumnFilters,sort:{key:ColumnKey;direction:1|-1}|null,manualOrder:string[]|null=null){
  const data=filteredRecords(records,filters);
  if(manualOrder){const rank=new Map(manualOrder.map((sku,index)=>[sku,index]));data.sort((a,b)=>(rank.get(a.product.sku)??Number.MAX_SAFE_INTEGER)-(rank.get(b.product.sku)??Number.MAX_SAFE_INTEGER));}
  if(sort)data.sort((a,b)=>a.values[sort.key].localeCompare(b.values[sort.key],undefined,{numeric:true})*sort.direction);
  return data.map(row=>row.product);
}
export function CatalogSheet(props: CatalogSheetProps) {
  const [customerView, setCustomerView] = useState<"catalog" | "workbook">("catalog");
  if (!props.canManageCatalogOrder && customerView === "catalog") {
    return <CustomerCatalog {...props} onShowWorkbook={() => setCustomerView("workbook")} />;
  }
  return <WorkbookCatalogSheet {...props} onShowCards={props.canManageCatalogOrder ? undefined : () => setCustomerView("catalog")} />;
}

function WorkbookCatalogSheet({products,search,onSearchChange,draft,publishedCatalogDraft,loading,loadError,storageFailed,onRetry,onUpdate,onToggle,onEdit,onNotify,onOpenDrive,onSetCover,onUndo,onRedo,canUndo,canRedo,catalogOrderOwner,canManageCatalogOrder,catalogOrderLoading,catalogOrderSaving,catalogOrderError,onSaveCatalogOrder,onSaveCatalogOrderOnly,onShowCards}:Props){
  const [sheet,setSheet]=useState<"all"|"selected">("all");
  const [filters,setFilters]=useState<ColumnFilters>({});
  const [sort,setSort]=useState<{key:ColumnKey;direction:1|-1}|null>(null);
  const [manualOrder,setManualOrder]=useState<string[]|null>(null);
  const [rowMove,setRowMove]=useState<{sku:string;source:number;target:number}|null>(null);
  const [range,setRange]=useState<CellRange>(EMPTY_RANGE),[editor,setEditor]=useState<Editor|null>(null);
  const [viewport,setViewport]=useState({top:0,height:650});
  const [sizePreview,setSizePreview]=useState<{key:string;size:number;row:boolean}|null>(null);
  const [filterMenu,setFilterMenu]=useState<{key:ColumnKey;x:number;y:number}|null>(null);
  const [gallery,setGallery]=useState<{product:MaterialProduct;importedPhoto:string}|null>(null);
  const [busy,setBusy]=useState(""); const [nameInput,setNameInput]=useState<string|null>(null);
  const [importSummary,setImportSummary]=useState<ImportSkuSummary|null>(null);
  const [customerDefaultsApplied,setCustomerDefaultsApplied]=useState(canManageCatalogOrder);
  const importReportRef=useRef(0);
  const grid=useRef<HTMLDivElement>(null),fileInput=useRef<HTMLInputElement>(null),editInput=useRef<HTMLTextAreaElement>(null),allCheckbox=useRef<HTMLInputElement>(null),autoSaveTimer=useRef<number|null>(null),arrangeMenu=useRef<HTMLDetailsElement>(null);
  const cleanupDrag=useRef<(()=>void)|null>(null);
  const rowMoveRef=useRef<{sku:string;source:number;target:number}|null>(null);
  const ignoreBlur=useRef(false);
  const copied=useRef<{text:string;matrix:string[][];range:CellRange;columns:ColumnKey[]}|null>(null);
  const latest=useRef({draft,range});latest.current={draft,range};
  const savedLayout=layoutOf(draft),layout=!canManageCatalogOrder&&!customerDefaultsApplied?defaultCustomerLayout(draft):savedLayout,sheetColumns=columnsForCatalog(canManageCatalogOrder),visible=sheetColumns.filter(c=>!layout.hidden.includes(c.key));
  const keys=visible.map(c=>c.key),available=useMemo(()=>products.filter(isQuotable),[products]);
  const salesWarehouseName=available.find(product=>product.salesWarehouseName)?.salesWarehouseName||"";
  const inventoryMeta=useMemo(()=>{
    const states=available.map(product=>product.inventoryState).filter(Boolean);
    if(!states.length)return null;
    const state=states.includes("live")?"live":states.includes("stale")?"stale":states.includes("unavailable")?"unavailable":"disabled";
    const updatedAt=available.map(product=>product.inventoryUpdatedAt||"").sort().at(-1)||"";
    const date=updatedAt?new Date(updatedAt):null;
    const time=date&&!Number.isNaN(date.getTime())?new Intl.DateTimeFormat("en-US",{hour:"2-digit",minute:"2-digit"}).format(date):"";
    const label=state==="live"?`Inventory live${time?` · ${time}`:""}`:state==="stale"?`Inventory cached${time?` · ${time}`:""}`:state==="unavailable"?"Inventory unavailable · Excel fallback":"Inventory source not configured · Excel fallback";
    return {state,label};
  },[available]);
  const selected=useMemo(()=>quoteProducts(draft,products),[draft,products]),selectedSet=new Set(draft.order);
  const makeFilterRecords=(source:MaterialProduct[])=>{
    const calculator=createCalculator(draft,source,sheetColumns),needle=search.trim().toLowerCase();
    return source.map((product,r):FilterRecord<MaterialProduct>=>({product,values:Object.fromEntries(sheetColumns.map(({key})=>[key,key==="photo"?(calculator.raw(r,key)?"Has image":""):String(calculator.cell(r,key))])) as Record<ColumnKey,string>}))
      .filter(({values})=>!needle||[values.sku,values.name,values.chineseName,values.brand,values.category,values.listingDate].join(" ").toLowerCase().includes(needle));
  };
  const availableFilterRecords=useMemo(()=>makeFilterRecords(available),[available,draft,search,sheetColumns]);
  const selectedFilterRecords=useMemo(()=>makeFilterRecords(selected),[selected,draft,search,sheetColumns]);
  const filterRecords=sheet==="selected"?selectedFilterRecords:availableFilterRecords;
  const rows=useMemo(()=>orderedProducts(filterRecords,filters,sort,manualOrder),[filterRecords,filters,sort,manualOrder]);
  const availableCount=useMemo(()=>filteredRecords(availableFilterRecords,filters).length,[availableFilterRecords,filters]);
  const selectedCount=useMemo(()=>filteredRecords(selectedFilterRecords,filters).length,[selectedFilterRecords,filters]);
  const menuOptions=useMemo(()=>filterMenu?filterOptions(filterRecords,filters,filterMenu.key):[],[filterRecords,filters,filterMenu?.key]);
  const calc=useMemo(()=>createCalculator(draft,rows,sheetColumns),[draft,rows,sheetColumns]);
  const totals=sheetTotals(draft,selected),b=bounds(range);
  const width=(key:ColumnKey)=>sizePreview&&!sizePreview.row&&sizePreview.key===key?sizePreview.size:layout.widths[key]||COLUMNS.find(c=>c.key===key)!.width;
  const height=(sku:string)=>sizePreview?.row&&sizePreview.key===sku?sizePreview.size:layout.heights[sku]||86;
  const prefix=[0];for(const p of rows)prefix.push(prefix.at(-1)!+height(p.sku));
  const rowAt=(y:number)=>{let lo=0,hi=rows.length;while(lo<hi){const mid=(lo+hi)>>1;if(prefix[mid+1]<=y)lo=mid+1;else hi=mid;}return Math.max(0,Math.min(rows.length-1,lo));};
  const startRow=Math.max(0,rowAt(Math.max(0,viewport.top-HEADER))-5),endRow=Math.min(rows.length,rowAt(Math.max(0,viewport.top-HEADER)+viewport.height)+7);
  const active=rows[range.start.r],activeKey=keys[range.start.c];
  const address=rows.length&&activeKey?rangeAddress(range,keys,sheetColumns):"A3";
  const activeRaw=active&&activeKey?calc.raw(range.start.r,activeKey):"";
  const allSelected=rows.length>0&&rows.every(p=>selectedSet.has(p.sku));
  const colLeft=(c:number)=>GUTTER+visible.slice(0,c).reduce((n,v)=>n+width(v.key),0);
  const frozen=(key:ColumnKey)=>layout.freeze&&sheetColumns.findIndex(c=>c.key===key)<=sheetColumns.findIndex(c=>c.key==="photo");
  const frozenWidth=GUTTER+visible.filter(c=>frozen(c.key)).reduce((n,c)=>n+width(c.key),0);
  const patchLayout=(patch:Partial<SheetLayout>)=>onUpdate(d=>({...d,layout:{...layoutOf(d),...patch}}));
  const priceRanges=layout.priceRanges||{tier1Max:29,tier2Max:50};
  const savePriceRange=(key:"tier1Max"|"tier2Max",value:string)=>{
    const number=Number(value);
    const minimum=key==="tier1Max"?1:2;
    const maximum=key==="tier1Max"?999_999:1_000_000;
    if(!Number.isInteger(number)||number<minimum||number>maximum){onNotify(`Price range limits must be whole numbers between ${minimum} and ${maximum.toLocaleString()}.`);return;}
    const next=key==="tier1Max"
      ?{tier1Max:number,tier2Max:Math.max(priceRanges.tier2Max,number+1)}
      :{tier1Max:Math.min(priceRanges.tier1Max,Math.max(1,number-1)),tier2Max:number};
    const labels={...(layout.labels||{})};delete labels.price;delete labels.priceBulk;
    patchLayout({priceRanges:next,labels});
  };
  const canEdit=(key:ColumnKey)=>canEditCatalogColumn(canManageCatalogOrder,key);
  const hasViewFilter=Boolean(search.trim())||Object.values(filters).some(Boolean);
  const canMoveRows=canManageCatalogOrder&&sheet==="all"&&!hasViewFilter&&!busy&&!catalogOrderLoading;
  const currentCatalogFingerprint=useMemo(()=>catalogDraftFingerprint(draft),[draft]);
  const publishedCatalogFingerprint=useMemo(()=>catalogDraftFingerprint(publishedCatalogDraft),[publishedCatalogDraft]);
  const hasUnpublishedChanges=canManageCatalogOrder&&!catalogOrderLoading&&currentCatalogFingerprint!==publishedCatalogFingerprint;
  useEffect(()=>{const el=grid.current;if(!el)return;const observer=new ResizeObserver(()=>setViewport(v=>({...v,height:el.clientHeight})));observer.observe(el);return()=>observer.disconnect();},[]);
  useEffect(()=>{if(canManageCatalogOrder||customerDefaultsApplied)return;setCustomerDefaultsApplied(true);if(savedLayout.hidden.some(key=>columnsForCatalog(false).some(column=>column.key===key)))onUpdate(current=>({...current,layout:defaultCustomerLayout(current)}));},[canManageCatalogOrder,customerDefaultsApplied,onUpdate,savedLayout.hidden]);
  useEffect(()=>()=>{cleanupDrag.current?.();if(autoSaveTimer.current!==null)window.clearTimeout(autoSaveTimer.current);},[]);
  useEffect(()=>{setRange(EMPTY_RANGE);setEditor(null);if(grid.current)grid.current.scrollTop=0;},[search,filters,sort,sheet,layout.hidden.join(",")]);
  useEffect(()=>{if(allCheckbox.current)allCheckbox.current.indeterminate=!allSelected&&rows.some(p=>selectedSet.has(p.sku));});
  useEffect(()=>{if(editor?.mode==="cell"){editInput.current?.focus();editInput.current?.setSelectionRange(editor.text.length,editor.text.length);}},[editor?.sku,editor?.key,editor?.mode]);
  useEffect(()=>{if(!filterMenu)return;const close=(e:Event)=>{if(!(e.target as HTMLElement).closest(".wb-column-filter,.wb-heading-button"))setFilterMenu(null);};document.addEventListener("pointerdown",close);return()=>document.removeEventListener("pointerdown",close);},[filterMenu]);
  useEffect(()=>{if(!hasUnpublishedChanges)return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue="";};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn);},[hasUnpublishedChanges]);
  const changeCells=(changes:CellChange[])=>{try{const allowed=changes.filter(change=>canEdit(change.key));if(!allowed.length)return true;const next=applyCellChanges(latest.current.draft,allowed,rows,!canManageCatalogOrder);onUpdate(()=>next);return true;}catch(e){onNotify(e instanceof Error?e.message:"Cells could not be updated.");return false;}};
  const applySort=(key:ColumnKey,direction:1|-1)=>{
    const nextSort={key,direction};
    const nextRows=orderedProducts(filterRecords,filters,nextSort,manualOrder);
    setSort(nextSort);setManualOrder(null);setFilterMenu(null);
    if(!canManageCatalogOrder||sheet!=="all")return;
    if(autoSaveTimer.current!==null)window.clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current=window.setTimeout(()=>{
      autoSaveTimer.current=null;
      void onSaveCatalogOrderOnly(completeCatalogOrder(nextRows,available))
        .then(()=>onNotify("Customer table order saved. Your customers will see this order."))
        .catch(error=>onNotify(error instanceof Error?error.message:"Customer table order could not be saved."));
    },250);
  };
  const publishRowOrder=(ordered:MaterialProduct[],message:string)=>{
    const skuOrder=completeCatalogOrder(ordered,available);
    setManualOrder(skuOrder);setSort(null);setFilterMenu(null);arrangeMenu.current?.removeAttribute("open");
    void onSaveCatalogOrderOnly(skuOrder).then(()=>onNotify(message)).catch(error=>onNotify(error instanceof Error?error.message:"Customer table order could not be saved."));
  };
  const groupRows=(key:CatalogGroupKey,label:string)=>publishRowOrder(groupCatalogProducts(available,key),`Grouped by ${label}. Your customers will see this order.`);
  const moveRow=(sku:string,target:number)=>{
    const moved=moveCatalogProduct(rows,sku,target);
    if(moved===rows||moved.every((product,index)=>product.sku===rows[index]?.sku))return;
    publishRowOrder(moved,"Custom row order saved. Your customers will see this order.");
    setRange(current=>({start:{r:Math.max(0,Math.min(moved.length-1,target)),c:current.start.c},end:{r:Math.max(0,Math.min(moved.length-1,target)),c:current.start.c}}));
  };
  const startRowMove=(e:ReactPointer,sku:string,source:number)=>{
    if(!canMoveRows)return;e.preventDefault();e.stopPropagation();if(!commit())return;cleanupDrag.current?.();
    const initial={sku,source,target:source};rowMoveRef.current=initial;setRowMove(initial);let mouse={x:e.clientX,y:e.clientY},frame=0;
    const tick=()=>{const el=grid.current;if(!el)return;const rect=el.getBoundingClientRect();if(mouse.y>rect.bottom-28)el.scrollTop+=18;else if(mouse.y<rect.top+HEADER+18)el.scrollTop-=18;const row=document.elementFromPoint(mouse.x,mouse.y)?.closest<HTMLTableRowElement>("tr[data-row]");const target=Number(row?.dataset.row);if(Number.isInteger(target)&&target>=0&&target<rows.length&&rowMoveRef.current&&rowMoveRef.current.target!==target){const next={...rowMoveRef.current,target};rowMoveRef.current=next;setRowMove(next);}frame=requestAnimationFrame(tick);};
    const move=(event:globalThis.PointerEvent)=>{mouse={x:event.clientX,y:event.clientY};};
    const stop=()=>{cancelAnimationFrame(frame);window.removeEventListener("pointermove",move);window.removeEventListener("pointerup",finish);window.removeEventListener("pointercancel",cancel);cleanupDrag.current=null;setRowMove(null);};
    const finish=()=>{const result=rowMoveRef.current;rowMoveRef.current=null;stop();if(result&&result.target!==result.source)moveRow(result.sku,result.target);};
    const cancel=()=>{rowMoveRef.current=null;stop();};
    cleanupDrag.current=cancel;window.addEventListener("pointermove",move);window.addEventListener("pointerup",finish);window.addEventListener("pointercancel",cancel);frame=requestAnimationFrame(tick);
  };
  const cancelEdit=()=>{ignoreBlur.current=true;setEditor(null);grid.current?.focus();};
  const commit=()=>{if(!editor)return true;const ok=changeCells([{sku:editor.sku,key:editor.key,value:editor.text,row:editor.row}]);if(ok)setEditor(null);return ok;};
  const selectCell=(p:Point,extend=false)=>{if(!rows.length||!keys.length)return;const point={r:Math.max(0,Math.min(rows.length-1,p.r)),c:Math.max(0,Math.min(keys.length-1,p.c))};setRange(current=>({start:extend?current.start:point,end:point}));grid.current?.focus({preventScroll:true});
    const el=grid.current;if(!el)return;const top=prefix[point.r]+HEADER,bottom=top+height(rows[point.r].sku);if(top<el.scrollTop+HEADER)el.scrollTop=prefix[point.r];else if(bottom>el.scrollTop+el.clientHeight)el.scrollTop=bottom-el.clientHeight;
    const left=colLeft(point.c),right=left+width(keys[point.c]);if(!frozen(keys[point.c])){if(left<el.scrollLeft+frozenWidth)el.scrollLeft=Math.max(0,left-frozenWidth);else if(right>el.scrollLeft+el.clientWidth)el.scrollLeft=right-el.clientWidth;}
  };
  const beginEdit=(text?:string,mode:Editor["mode"]="cell")=>{ignoreBlur.current=false;if(!active||!activeKey||!canEdit(activeKey))return;setRange({start:range.start,end:range.start});setEditor({sku:active.sku,key:activeKey,row:range.start.r+3,text:text??activeRaw,mode});};
  const rangeMatrix=(raw=false)=>{const matrix:string[][]=[];for(let r=b.r0;r<=Math.min(b.r1,rows.length-1);r++){const row:string[]=[];for(let c=b.c0;c<=Math.min(b.c1,keys.length-1);c++)row.push(keys[c]==="photo"?"":raw?calc.raw(r,keys[c]):String(calc.cell(r,keys[c])));matrix.push(row);}return matrix;};
  const copyData=()=>{const text=toTSV(rangeMatrix());copied.current={text,matrix:rangeMatrix(true),range,columns:keys};return text;};
  const pasteData=(text:string)=>{try{const matrix=fromTSV(text);if(!rows.length)return;const source=copied.current?.text===text?copied.current:null;const sourceBounds=source?bounds(source.range):null;const changes:CellChange[]=[];
    const h=matrix.length,w=Math.max(...matrix.map(r=>r.length)),targetH=Math.max(h,b.r1-b.r0+1),targetW=Math.max(w,b.c1-b.c0+1);
    if(b.r0+targetH>rows.length||b.c0+targetW>keys.length)throw Error("The clipboard range extends beyond this worksheet. Select a smaller starting range.");
    if(targetH%h||targetW%w)throw Error("The selected range must fit the copied rectangle.");
    for(let r=0;r<targetH;r++)for(let c=0;c<targetW;c++){const key=keys[b.c0+c];if(!canEdit(key))continue;let value=(source?.matrix||matrix)[r%h]?.[c%w]||"";
      if(value.startsWith("=")&&key==="amount"&&sourceBounds&&source){const oldCol=sheetColumns.findIndex(x=>x.key===source.columns[sourceBounds.c0+c%w]);value=shiftFormula(value,b.r0+r-sourceBounds.r0-r%h,sheetColumns.findIndex(x=>x.key===key)-oldCol);}
      changes.push({sku:rows[b.r0+r].sku,key,value,row:b.r0+r+3});}
    if(changeCells(changes))setRange({start:{r:b.r0,c:b.c0},end:{r:b.r0+targetH-1,c:b.c0+targetW-1}});
  }catch(e){onNotify(e instanceof Error?e.message:"Paste failed.");}};
  const clearCells=()=>{const changes:CellChange[]=[];for(let r=b.r0;r<=Math.min(b.r1,rows.length-1);r++)for(let c=b.c0;c<=b.c1;c++)if(keys[c])changes.push({sku:rows[r].sku,key:keys[c],value:"",row:r+3});changeCells(changes);};
  const keyDown=(e:KeyboardEvent<HTMLDivElement>)=>{
    if(e.target!==e.currentTarget||editor||busy)return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="z"){e.preventDefault();e.shiftKey?onRedo():onUndo();return;}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="y"){e.preventDefault();onRedo();return;}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="a"){e.preventDefault();setRange({start:{r:0,c:0},end:{r:rows.length-1,c:keys.length-1}});return;}
    if(e.key==="Enter"&&activeKey==="photo"&&active){e.preventDefault();setGallery({product:active,importedPhoto:draft.lines[active.sku]?.photoData||""});return;}
    const p=e.shiftKey?range.end:range.start;let next:Point|null=null;
    if(e.key==="ArrowDown")next={...p,r:p.r+1};if(e.key==="ArrowUp")next={...p,r:p.r-1};if(e.key==="ArrowLeft")next={...p,c:p.c-1};if(e.key==="ArrowRight")next={...p,c:p.c+1};
    if(e.key==="Home")next={r:e.ctrlKey?0:p.r,c:0};if(e.key==="End")next={r:e.ctrlKey?rows.length-1:p.r,c:keys.length-1};
    if(e.key==="Tab"){const n=p.r*keys.length+p.c+(e.shiftKey?-1:1);next={r:Math.floor(Math.max(0,n)/keys.length),c:Math.max(0,n)%keys.length};}
    if(e.key==="Enter")next={...p,r:p.r+(e.shiftKey?-1:1)};
    if(next){e.preventDefault();selectCell(next,e.shiftKey&&e.key!=="Tab"&&e.key!=="Enter");return;}
    if(e.key==="Delete"||e.key==="Backspace"){e.preventDefault();clearCells();return;}
    if(e.key==="Escape"){setRange({start:range.start,end:range.start});return;}
    if(e.key==="F2"){e.preventDefault();beginEdit();return;}
    if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key.length===1||e.key==="Process")){e.preventDefault();beginEdit(e.key==="Process"?"":e.key);}
  };
  const editorKey=(e:KeyboardEvent)=>{if(e.nativeEvent.isComposing)return;if(e.key==="Escape"){e.preventDefault();cancelEdit();}else if((e.key==="Enter"&&!e.altKey)||e.key==="Tab"){e.preventDefault();if(commit()){const p=range.start;selectCell(e.key==="Tab"?{r:p.r,c:p.c+(e.shiftKey?-1:1)}:{r:p.r+(e.shiftKey?-1:1),c:p.c});}}};
  const startGesture=(e:ReactPointer,point:Point,kind:"select"|"fill")=>{
    if(e.button!==0||busy)return;e.preventDefault();e.stopPropagation();if(!commit())return;cleanupDrag.current?.();grid.current?.focus({preventScroll:true});
    const original=kind==="fill"?range:{start:e.shiftKey?range.start:point,end:point};setRange(original);let end=original.end,mouse={x:e.clientX,y:e.clientY},frame=0,last="";
    const tick=()=>{const el=grid.current;if(!el)return;const rect=el.getBoundingClientRect();if(mouse.y>rect.bottom-25)el.scrollTop+=18;else if(mouse.y<rect.top+HEADER+14)el.scrollTop-=18;if(mouse.x>rect.right-25)el.scrollLeft+=16;else if(mouse.x<rect.left+GUTTER+14)el.scrollLeft-=16;
      const y=mouse.y-rect.top+el.scrollTop-HEADER;const localX=mouse.x-rect.left;const x=localX+(layout.freeze&&localX<frozenWidth?0:el.scrollLeft);let c=0;while(c<keys.length-1&&colLeft(c)+width(keys[c])<x)c++;
      end={r:rowAt(Math.max(0,y)),c:kind==="fill"?original.end.c:c};const newRange=kind==="fill"?{start:{r:Math.min(bounds(original).r0,end.r),c:bounds(original).c0},end:{r:Math.max(bounds(original).r1,end.r),c:bounds(original).c1}}:{start:original.start,end};const id=JSON.stringify(newRange);if(last!==id){setRange(newRange);last=id;}frame=requestAnimationFrame(tick);
    };
    const move=(event:globalThis.PointerEvent)=>{mouse={x:event.clientX,y:event.clientY};if(!frame)frame=requestAnimationFrame(tick);};
    const stop=()=>{cancelAnimationFrame(frame);window.removeEventListener("pointermove",move);window.removeEventListener("pointerup",finish);window.removeEventListener("pointercancel",stop);cleanupDrag.current=null;};
    const finish=()=>{stop();if(kind==="fill"){const a=bounds(original),target={start:{r:Math.min(a.r0,end.r),c:a.c0},end:{r:Math.max(a.r1,end.r),c:a.c1}};changeCells(fillChanges(latest.current.draft,rows,keys,original,target,sheetColumns));}};
    cleanupDrag.current=stop;window.addEventListener("pointermove",move);window.addEventListener("pointerup",finish);window.addEventListener("pointercancel",stop);
  };
  const resize=(e:ReactPointer,key:string,isRow:boolean)=>{e.preventDefault();e.stopPropagation();cleanupDrag.current?.();const origin=isRow?height(key):width(key as ColumnKey),start=isRow?e.clientY:e.clientX;let size=origin;
    const move=(event:globalThis.PointerEvent)=>{size=Math.round(Math.max(isRow?32:55,Math.min(isRow?300:600,origin+(isRow?event.clientY:event.clientX)-start)));setSizePreview({key,size,row:isRow});};
    const stop=()=>{window.removeEventListener("pointermove",move);window.removeEventListener("pointerup",finish);window.removeEventListener("pointercancel",cancel);cleanupDrag.current=null;setSizePreview(null);};
    const finish=()=>{stop();onUpdate(d=>{const l=layoutOf(d);return {...d,layout:{...l,[isRow?"heights":"widths"]:{...l[isRow?"heights":"widths"],[key]:size}}};});};const cancel=()=>stop();cleanupDrag.current=stop;window.addEventListener("pointermove",move);window.addEventListener("pointerup",finish);window.addEventListener("pointercancel",cancel);
  };
  const hideColumn=(key:ColumnKey,hide:boolean)=>{if(!commit())return;if(hide&&visible.length===1){onNotify("Keep at least one column visible.");return;}patchLayout({hidden:hide?[...new Set([...layout.hidden,key])]:layout.hidden.filter(k=>k!==key)});};
  const importFile=async(file:File)=>{
    const reportId=++importReportRef.current;
    setImportSummary(null);
    try{assertExcelImportSize(file.size);}catch(e){onNotify(e instanceof Error?e.message:"Excel import failed.");if(fileInput.current)fileInput.current.value="";return;}
    const sizeMb=Math.max(1,Math.round(file.size/1024/1024));setBusy(`Reading Excel · ${sizeMb} MB…`);
    try{
      const {readCatalogXlsx}=await import("./excelCatalog");
      const result=await readCatalogXlsx(new Uint8Array(await file.arrayBuffer()),available);
      const summary:ImportSkuSummary={searched:result.searched,matched:result.matched,missingSkus:result.missingSkus,duplicates:result.duplicates,notificationState:result.missingSkus.length?"sending":"idle"};
      setImportSummary(summary);
      if(result.missingSkus.length){
        void reportMissingSkus(result.missingSkus,result.searched,"excel_import")
          .then((notification)=>{
            if(importReportRef.current!==reportId)return;
            setImportSummary(current=>current?{...current,notificationState:"sent"}:current);
            onNotify(notification.duplicate
              ? `未找到的 ${result.missingSkus.length} 个 SKU 已提醒管理员，无需重复发送。`
              : `未找到的 ${result.missingSkus.length} 个 SKU 已发送给${notification.recipientName}添加。`);
          })
          .catch((error)=>{
            if(importReportRef.current!==reportId)return;
            setImportSummary(current=>current?{...current,notificationState:"error"}:current);
            onNotify(error instanceof Error?error.message:"未找到的 SKU 暂时无法通知管理员。");
          });
      }
      let next=applyCellChanges(draft,result.changes,available);const lines={...next.lines};
      for(const sku of result.skuOrder){const line=lines[sku];if(line?.photoData){const {photoData:_,...cellOnlyLine}=line;lines[sku]=cellOnlyLine;}}
      const importedLayout={...result.layout,...(layout.labels?{labels:{...layout.labels}}:{})};
      next={...next,lines,layout:importedLayout,currency:result.currency||draft.currency,title:result.title||draft.title};onUpdate(()=>next);let published=false,publishError="";
      if(canManageCatalogOrder){const imported=new Set(result.skuOrder);try{await onSaveCatalogOrder([...result.skuOrder,...available.filter(p=>!imported.has(p.sku)).map(p=>p.sku)],next);published=true;}catch(error){publishError=error instanceof Error?error.message:"Customer table could not be saved.";}}
      onNotify(`Imported ${result.matched} products.${published?" Customer catalog table saved.":publishError?` Saved in this browser; ${publishError}`:""} ${result.skipped} unknown/duplicate SKUs skipped.${result.warnings.length?` ${result.warnings.length} invalid cells left unchanged.`:""} Embedded pictures were ignored; website images are used by SKU.`);setRange(EMPTY_RANGE);
    }catch(e){const message=e instanceof Error?e.message:"";onNotify(/memory|allocation|invalid array length/i.test(message)?"This Excel file exceeded the memory available to this browser. Split the workbook into smaller files and try again.":message||"Excel import failed.");}
    finally{setBusy("");if(fileInput.current)fileInput.current.value="";}
  };
  const display=(r:number,key:ColumnKey)=>{const value=calc.cell(r,key);if(typeof value==="number"&&["price","priceBulk","msrp","amount"].includes(key))return formatMoney(Math.round(value*100),draft.currency);return String(value);};
  const goToName=()=>{const [a,z]=String(nameInput||"").split(":"),first=parseAddress(a),last=parseAddress(z||a);if(first&&last&&first.row>=3&&last.row>=3&&first.row<=rows.length+2&&last.row<=rows.length+2){const c=keys.indexOf(sheetColumns[first.col]?.key),ec=keys.indexOf(sheetColumns[last.col]?.key);if(c>=0&&ec>=0){selectCell({r:first.row-3,c});setRange({start:{r:first.row-3,c},end:{r:last.row-3,c:ec}});}else onNotify("Show the hidden column before selecting that address.");}else onNotify("Enter a cell or range, for example F3 or F3:G8.");setNameInput(null);};
  const shownFormula=editor?.mode==="formula"?editor.text:activeRaw;
  return <main className="catalog-sheet workbook-v3" aria-label="Product catalog workbook">
    <div className="wb-file-bar"><div className="wb-file-title" title={draft.title}><Table size={19} aria-hidden="true"/>{inventoryMeta&&<span className={`wb-inventory-source is-${inventoryMeta.state}`} title="Available inventory from the inventory workbench; imported Excel is used only when live inventory is unavailable."><Database size={13} weight="bold"/>{inventoryMeta.label}</span>}</div><ProductSearch value={search} onChange={onSearchChange} className="wb-file-search"/><div className="wb-file-actions" inert={!!busy || undefined}>{onShowCards&&<button type="button" onClick={onShowCards}>Picture catalog</button>}{canManageCatalogOrder&&<button className={`wb-save-customer-order${hasUnpublishedChanges?" is-unpublished":""}`} disabled={!!busy||catalogOrderLoading||catalogOrderSaving||!available.length||!hasUnpublishedChanges} title={hasUnpublishedChanges?"Publish prices, notes, title, currency, columns and layout changes for your customers.":"All customer-visible table changes are published."} onClick={()=>{if(!commit())return;void onSaveCatalogOrder(completeCatalogOrder(rows,available),draft).then(()=>onNotify("Table changes published to your customers.")).catch(error=>onNotify(error instanceof Error?error.message:"Customer catalog table could not be published."));}}><FloppyDisk size={16}/>{catalogOrderSaving?"Saving…":"Publish table changes"}</button>}{canManageCatalogOrder&&<button disabled={!!busy||catalogOrderSaving} onClick={()=>fileInput.current?.click()}><UploadSimple size={16}/>Import Excel</button>}<QuoteBuilder draft={draft} products={products} displayedProducts={rows} canManageCatalogOrder={canManageCatalogOrder} onUpdate={onUpdate} onNotify={onNotify}/><input type="file" accept=".xlsx" ref={fileInput} hidden aria-label="Import Excel file" onChange={e=>{const file=e.target.files?.[0];if(file)void importFile(file );}}/></div></div>
    {importSummary&&<section className={`batch-search-summary wb-import-summary ${importSummary.missingSkus.length?"has-missing":"is-complete"}`} aria-label="管理员 Excel 导入摘要">
      <div className="batch-search-counts"><span><small>导入</small><strong>{importSummary.searched}</strong></span><span><small>找到</small><strong>{importSummary.matched}</strong></span><span><small>未找到</small><strong>{importSummary.missingSkus.length}</strong></span></div>
      {importSummary.missingSkus.length?<details><summary>查看未找到的 SKU</summary><div className="batch-missing-skus">{importSummary.missingSkus.slice(0,100).map(sku=><code key={sku}>{sku}</code>)}{importSummary.missingSkus.length>100&&<span>另有 {importSummary.missingSkus.length-100} 个，已一并发送</span>}{importSummary.duplicates>0&&<span>另跳过 {importSummary.duplicates} 个重复 SKU</span>}</div></details>:<strong className="batch-search-complete">全部 SKU 均已找到</strong>}
      {importSummary.missingSkus.length>0&&<span className={`batch-notification-state is-${importSummary.notificationState}`}>{importSummary.notificationState==="sending"?"正在通知管理员…":importSummary.notificationState==="sent"?"未搜索到的已发送给管理员添加":importSummary.notificationState==="error"?"通知失败，请重新导入后重试":"准备通知管理员"}</span>}
    </section>}
    <div className="wb-tools" inert={!!busy || undefined} aria-label="Workbook tools">
      <button aria-label="Undo" title="Undo (Ctrl+Z)" disabled={!canUndo&&!editor} onMouseDown={e=>e.preventDefault()} onClick={()=>{editor?cancelEdit():onUndo();grid.current?.focus();}}><ArrowCounterClockwise size={17}/></button><button aria-label="Redo" title="Redo (Ctrl+Y)" disabled={!canRedo} onClick={onRedo}><ArrowClockwise size={17}/></button><i/>
      <button onClick={async()=>{try{await navigator.clipboard.writeText(copyData());onNotify("Selected cells copied.");}catch{onNotify("Select cells and press Ctrl+C to copy.");}}}><Copy size={16}/>Copy</button><button onClick={async()=>{try{pasteData(await navigator.clipboard.readText());}catch{onNotify("Select a cell and press Ctrl+V to paste.");}}}><ClipboardText size={16}/>Paste</button><button onClick={clearCells}><Trash size={16}/>Clear</button><i/>
      {canManageCatalogOrder&&<details className="wb-arrange" ref={arrangeMenu}><summary><ListBullets size={16}/>Arrange<CaretDown size={10}/></summary><div><strong>Group customer table</strong><small>Start with a group, then drag row handles to fine-tune the order.</small><button disabled={catalogOrderLoading} onClick={()=>groupRows("category","category")}>Category</button><button disabled={catalogOrderLoading} onClick={()=>groupRows("series","series / theme")}>Series / theme</button><button disabled={catalogOrderLoading} onClick={()=>groupRows("set","product set")}>Product set</button><button disabled={catalogOrderLoading} onClick={()=>groupRows("brand","brand")}>Brand</button><button disabled={catalogOrderLoading} onClick={()=>groupRows("sku","SKU")}>SKU</button></div></details>}
      <details className="wb-columns"><summary><Columns size={16}/>Columns<CaretDown size={10}/></summary><div>{canManageCatalogOrder&&<section className="wb-column-labels"><strong>Price quantity ranges</strong><label><span>Tier 1</span><span className="wb-range-fields"><b>1–</b><input key={`tier1-${priceRanges.tier1Max}`} type="number" min="1" max="999999" aria-label="First price range maximum quantity" defaultValue={priceRanges.tier1Max} onClick={e=>e.stopPropagation()} onBlur={e=>savePriceRange("tier1Max",e.currentTarget.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();e.currentTarget.blur();}else if(e.key==="Escape"){e.currentTarget.value=String(priceRanges.tier1Max);e.currentTarget.blur();}}}/><b>PCS</b></span></label><label><span>Tier 2</span><span className="wb-range-fields"><b>{priceRanges.tier1Max+1}–</b><input key={`tier2-${priceRanges.tier2Max}`} type="number" min="2" max="1000000" aria-label="Second price range maximum quantity" defaultValue={priceRanges.tier2Max} onClick={e=>e.stopPropagation()} onBlur={e=>savePriceRange("tier2Max",e.currentTarget.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();e.currentTarget.blur();}else if(e.key==="Escape"){e.currentTarget.value=String(priceRanges.tier2Max);e.currentTarget.blur();}}}/><b>PCS</b></span></label><small>Updates customer pricing, column headings and Excel formulas.</small></section>}{sheetColumns.map(c=><label key={c.key}><input type="checkbox" checked={!layout.hidden.includes(c.key)} onChange={e=>hideColumn(c.key,!e.target.checked)}/>{columnLabel(c,salesWarehouseName,layout.labels,layout.priceRanges).replace("\n"," ")}</label>)}<button onClick={()=>patchLayout({hidden:[]})}>Show all</button></div></details>
      <button className={layout.freeze?"is-on":""} aria-pressed={layout.freeze} onClick={()=>patchLayout({freeze:!layout.freeze})} title="Freeze columns through PHOTO, including SKU"><Snowflake size={16}/>Freeze PHOTO + SKU</button><i/>
      <label className="wb-currency">Currency<select aria-label="Workbook currency" value={draft.currency} disabled={!canManageCatalogOrder} onChange={e=>{const currency=e.target.value;onUpdate(d=>({...d,currency}));}}>{["USD","EUR","GBP","CAD","AUD","CNY","JPY"].map(c=><option key={c}>{c}</option>)}</select></label>
      <button disabled={!Object.values(filters).some(Boolean)} onClick={()=>setFilters({})}><Funnel size={15}/>Clear filters</button><span className="wb-tool-spacer"/><small>{selected.length} selected</small><button aria-label="Clear selected products" disabled={!selected.length} onClick={()=>onToggle(selected.map(p=>p.sku),false)}><X size={15}/></button>
    </div>
    <div className="wb-formula" inert={!!busy || undefined}><input aria-label="Name box" value={nameInput??address} onFocus={()=>setNameInput(address)} onChange={e=>setNameInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter")goToName();if(e.key==="Escape")setNameInput(null);}} onBlur={()=>setNameInput(null)}/><span>fx</span><input className="wb-formula-input" aria-label="Formula bar" value={shownFormula} readOnly={!active||!activeKey||!canEdit(activeKey)} placeholder="Select a cell · double-click or type to edit" onFocus={()=>{if(editor)setEditor({...editor,mode:"formula"});else beginEdit(undefined,"formula");}} onChange={e=>setEditor(current=>current?{...current,text:e.target.value}:current)} onKeyDown={editorKey} onBlur={()=>{if(editor?.mode==="formula")commit( );}}/>{editor&&<button aria-label="Cancel cell edit" onMouseDown={e=>e.preventDefault()} onClick={cancelEdit}><X size={14}/></button>}</div>
    {busy&&<div className="wb-busy" role="status">{busy}</div>}
    <div className="wb-grid-scroll" inert={!!busy || undefined} role="grid" aria-label="Catalog cells" aria-rowcount={rows.length+3} aria-colcount={visible.length} tabIndex={0} ref={grid} onKeyDown={keyDown} onCopy={e=>{if(editor)return;e.preventDefault();e.clipboardData.setData("text/plain",copyData());}} onPaste={e=>{if(editor)return;e.preventDefault();pasteData(e.clipboardData.getData("text/plain"));}} onScroll={e=>{const top=e.currentTarget.scrollTop;setViewport(v=>({...v,top}));}} style={{"--wb-frozen-width":`${layout.freeze?frozenWidth:GUTTER}px`} as CSSProperties}>
      {loadError?<div className="wb-state" role="alert">{loadError}<button onClick={onRetry}>Retry</button></div>:loading&&!rows.length?<div className="wb-state">Loading catalog…</div>:<>
        <table className="wb-grid" role="presentation" style={{width:GUTTER+visible.reduce((n,c)=>n+width(c.key),0)}}><colgroup><col style={{width:GUTTER}}/>{visible.map(c=><col key={c.key} style={{width:width(c.key)}}/>)}</colgroup>
          <thead><tr className="wb-letters"><th className="wb-gutter"/><>{visible.map((col,c)=><th key={col.key} style={frozen(col.key)?{left:colLeft(c),zIndex:11}:undefined} className={frozen(col.key)?"wb-frozen":""}>{columnLetter(sheetColumns.findIndex(k=>k.key===col.key))}<button className="wb-col-resize" aria-label={`Resize ${col.key} column`} onPointerDown={e=>resize(e,col.key,false)} onKeyDown={e=>{if(["ArrowLeft","ArrowRight"].includes(e.key)){e.preventDefault();patchLayout({widths:{...layout.widths,[col.key]:Math.max(55,Math.min(600,width(col.key)+(e.key==="ArrowRight"?12:-12)))}});}}}/></th>)}</></tr>
          <tr className="wb-title-row"><th className="wb-gutter">1</th><th colSpan={visible.length}><input aria-label="Catalog heading" maxLength={120} value={draft.title} readOnly={!canManageCatalogOrder} onChange={e=>{const title=e.target.value;onUpdate(d=>({...d,title}) );}}/></th></tr>
          <tr className="wb-headings"><th className="wb-gutter"><span>2</span><input ref={allCheckbox} aria-label="Select all products in sheet" type="checkbox" checked={allSelected} onChange={e=>onToggle(rows.map(p=>p.sku),e.target.checked)}/></th>{visible.map((col,c)=><th key={col.key} className={frozen(col.key)?"wb-frozen":""} style={frozen(col.key)?{left:colLeft(c),zIndex:11}:undefined}><button className="wb-heading-button" aria-label={`Filter ${col.key} column`} aria-haspopup="dialog" data-filtered={!!filters[col.key]} aria-expanded={filterMenu?.key===col.key} aria-controls={filterMenu?.key===col.key?"workbook-column-filter":undefined} onClick={e=>{const rect=e.currentTarget.getBoundingClientRect();setFilterMenu(current=>current?.key===col.key?null:{key:col.key,x:Math.max(8,Math.min(rect.left,window.innerWidth-448)),y:Math.max(8,Math.min(rect.bottom+3,window.innerHeight-300))});}}><span>{columnLabel(col,salesWarehouseName,layout.labels,layout.priceRanges)}</span><Funnel size={11} weight={filters[col.key]?"fill":"regular"}/></button></th>)}</tr></thead>
          <tbody>{startRow>0&&<tr aria-hidden="true"><td colSpan={visible.length+1} className="wb-spacer" style={{height:prefix[startRow]}}/></tr>}{rows.slice(startRow,endRow).map((p,index)=>{const r=startRow+index,h=height(p.sku);return <tr key={p.sku} role="row" aria-rowindex={r+4} data-row={r} className={rowMove?.sku===p.sku?"wb-row-dragging":rowMove?.target===r?"wb-row-drop-target":""} style={{height:h}}><th className="wb-gutter wb-row-number"><label><span>{r+3}</span><input aria-label={`Select product ${p.sku}`} type="checkbox" checked={selectedSet.has(p.sku)} onChange={e=>onToggle([p.sku],e.target.checked)}/></label>{canManageCatalogOrder&&sheet==="all"&&<button className="wb-row-move" aria-label={`Move row ${r+3}, SKU ${p.sku}`} title={canMoveRows?"Drag to set a custom customer-table order":"Clear search and filters before dragging rows"} disabled={!canMoveRows} onPointerDown={e=>startRowMove(e,p.sku,r)} onKeyDown={e=>{if(e.key==="ArrowUp"||e.key==="ArrowDown"){e.preventDefault();moveRow(p.sku,r+(e.key==="ArrowDown"?1:-1));}}}><DotsSixVertical size={14} weight="bold"/></button>}<button className="wb-row-resize" aria-label={`Resize row ${r+3}`} onPointerDown={e=>resize(e,p.sku,true)} onKeyDown={e=>{if(["ArrowUp","ArrowDown"].includes(e.key)){e.preventDefault();patchLayout({heights:{...layout.heights,[p.sku]:Math.max(32,Math.min(300,h+(e.key==="ArrowDown"?8:-8)))}});}}}/></th>
            {visible.map((col,c)=>{const inRange=r>=b.r0&&r<=b.r1&&c>=b.c0&&c<=b.c1,isActive=range.start.r===r&&range.start.c===c,isEditing=editor?.mode==="cell"&&editor.sku===p.sku&&editor.key===col.key;const src=rawValue(draft,p,"photo",r+3);return <td key={col.key} role="gridcell" aria-label={`${col.key} ${columnLetter(sheetColumns.findIndex(k=>k.key===col.key))}${r+3}`} aria-selected={inRange} data-row={r} data-col={c} title={col.key==="photo"?"Click or press Enter to view all product images":undefined} className={["wb-cell",col.numeric?"wb-numeric":"",["name","chineseName","category"].includes(col.key)?"wb-text":"",col.key==="note"?"wb-note":"",frozen(col.key)?"wb-frozen":"",inRange?"wb-range":"",isActive?"wb-active":"",inRange&&r===b.r0?"wb-range-top":"",inRange&&r===b.r1?"wb-range-bottom":"",inRange&&c===b.c0?"wb-range-left":"",inRange&&c===b.c1?"wb-range-right":"",col.key==="photo"?"wb-photo":""].join(" ")} style={{height:h,...(frozen(col.key)?{left:colLeft(c)}:{})}} onPointerDown={e=>{if((e.target as HTMLElement).closest("textarea,button,input"))return;startGesture(e,{r,c},"select");}} onClick={()=>{if(col.key==="photo")setGallery({product:p,importedPhoto:draft.lines[p.sku]?.photoData||""});}} onDoubleClick={()=>{if(col.key==="photo")return;ignoreBlur.current=false;setRange({start:{r,c},end:{r,c}});if(canEdit(col.key))setEditor({sku:p.sku,key:col.key,row:r+3,text:calc.raw(r,col.key),mode:"cell"});}}>
              {col.key==="photo"?(src?<AssetImage src={src.startsWith("data:")?src:thumbnailVariantUrl(src,"small")} alt={p.name} loading="lazy"/>:<span>—</span>):<span className={String(calc.cell(r,col.key)).startsWith("#")?"wb-cell-error":""}>{display(r,col.key)}</span>}
              {isEditing&&<textarea ref={editInput} aria-label={`Edit ${columnLetter(sheetColumns.findIndex(k=>k.key===col.key))}${r+3}`} value={editor.text} onChange={e=>setEditor({...editor,text:e.target.value})} onKeyDown={editorKey} onBlur={e=>{if(ignoreBlur.current)return;if((e.relatedTarget as HTMLElement)?.classList.contains("wb-formula-input"))setEditor({...editor,mode:"formula"});else commit( );}}/>}
              {r===b.r1&&c===b.c1&&inRange&&!editor&&canEdit(col.key)&&<button className="wb-fill-handle" aria-label="Drag to fill selected cells" title="Drag down to fill values or a number series" onPointerDown={e=>startGesture(e,{r,c},"fill")}/>}
            </td>;})}</tr>;})}{endRow<rows.length&&<tr aria-hidden="true"><td className="wb-spacer" colSpan={visible.length+1} style={{height:prefix.at(-1)!-prefix[endRow]}}/></tr>}</tbody>
        </table>{!rows.length&&<div className="wb-state">{sheet==="selected"?"Select products in the catalog to build your customer worksheet.":"No matching products. Clear the search or column filters."}</div>}
      </>}
    </div>
    <footer className="wb-status"><div role="tablist" aria-label="Workbook sheets"><button role="tab" aria-selected={sheet==="all"} onClick={()=>{commit();setSheet("all");}}>Accessories <small>{availableCount}</small></button><button role="tab" aria-selected={sheet==="selected"} onClick={()=>{commit();setSheet("selected");}}>Selected products <small>{selectedCount}</small></button></div><span>{editor?"Edit":"Ready"} · {Math.max(0,b.r1-b.r0+1)} × {Math.max(0,b.c1-b.c0+1)} cells</span>{canManageCatalogOrder?<span className="wb-status-total">{rows.length.toLocaleString()} products</span>:<span className="wb-status-total">Qty: {totals.quantity.toLocaleString()} · {totals.unpriced?"Priced total":"Total"}: {formatMoney(totals.amountCents,draft.currency)}{totals.unpriced?` · ${totals.unpriced} need a quote`:""}</span>}</footer>
    {filterMenu&&<ColumnFilterMenu key={filterMenu.key} column={filterMenu.key} label={columnLabel(COLUMNS.find(c=>c.key===filterMenu.key)!,salesWarehouseName,layout.labels,layout.priceRanges).replace("\n"," ")} x={filterMenu.x} y={filterMenu.y} options={menuOptions} filter={filters[filterMenu.key]} sortDirection={sort?.key===filterMenu.key?sort.direction:undefined} onClose={()=>setFilterMenu(null)} onSort={direction=>applySort(filterMenu.key,direction)} onApply={filter=>{setFilters(current=>{const next={...current};if(filter)next[filterMenu.key]=filter;else delete next[filterMenu.key];return next;});setFilterMenu(null);}}/>}
    {gallery&&<ProductImageGallery product={gallery.product} importedPhoto={gallery.importedPhoto} onOpenDrive={()=>onOpenDrive(gallery.product)} canSetCover={canManageCatalogOrder} onSetCover={onSetCover} onNotify={onNotify} onClose={()=>{setGallery(null);grid.current?.focus();}}/>}
  </main>;
}

