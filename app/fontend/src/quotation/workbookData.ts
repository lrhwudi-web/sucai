import type { MaterialProduct } from "../types";
import { DEFAULT_PRICE_RANGES, emptyLine, priceRangesOf, type PriceRanges, type QuoteDraft, type QuoteLine, type SheetLayout } from "./quotation.ts";
import { columnLetter, evaluateFormula, expandFormulaRanges, parseAddress, shiftFormula, type FormulaValue } from "./formulas.ts";

export type ColumnKey = "brand" | "sku" | "name" | "chineseName" | "category" | "photo" | "price" | "priceBulk" | "msrp" | "listingDate" | "note" | "inventory" | "quantity" | "amount" | "salesWarehouseInventory" | "salesWarehouseAge181365" | "salesWarehouseAge366Plus" | "totalPendingQc" | "totalPendingArrival";
export type WorkbookColumn = {key:ColumnKey; label:string; width:number; numeric?:boolean; readonly?:boolean};
export const COLUMNS: WorkbookColumn[] = [
  {key:"brand",label:"BRAND",width:88},{key:"sku",label:"SKU",width:94,readonly:true},{key:"name",label:"ITEM",width:214},
  {key:"category",label:"CATEGORY",width:126},{key:"photo",label:"PHOTO",width:110,readonly:true},
  {key:"price",label:"U/P\n(1–29PCS)",width:106,numeric:true},{key:"priceBulk",label:"U/P\n(30–50PCS)",width:106,numeric:true},
  {key:"msrp",label:"MSRP",width:90,numeric:true},{key:"note",label:"NOTE",width:140},{key:"inventory",label:"INVENTORY",width:100,numeric:true},
  {key:"quantity",label:"ORDER QTY",width:98,numeric:true},{key:"amount",label:"AMOUNT",width:116,numeric:true},
  {key:"salesWarehouseInventory",label:"MY WAREHOUSE\nSTOCK",width:116,numeric:true,readonly:true},
  {key:"salesWarehouseAge181365",label:"MY WAREHOUSE\n181–365 DAYS",width:128,numeric:true,readonly:true},
  {key:"salesWarehouseAge366Plus",label:"MY WAREHOUSE\n366+ DAYS",width:124,numeric:true,readonly:true},
  {key:"totalPendingQc",label:"TOTAL\nPENDING QC",width:108,numeric:true,readonly:true},
  {key:"totalPendingArrival",label:"TOTAL\nPENDING ARRIVAL",width:108,numeric:true,readonly:true},
  {key:"chineseName",label:"中文品名",width:220,readonly:true},
  {key:"listingDate",label:"LISTING\nDATE",width:112,readonly:true},
];
const columnsByKey = new Map(COLUMNS.map(column=>[column.key,column]));
const columnSet = (keys:ColumnKey[]) => keys.map(key=>columnsByKey.get(key)!);
export const CUSTOMER_COLUMNS = columnSet(["brand","sku","name","category","photo","price","priceBulk","msrp","note","inventory","quantity","amount"]);
export const ADMIN_COLUMNS = columnSet(["brand","sku","name","chineseName","category","photo","price","priceBulk","msrp","listingDate","note","inventory","salesWarehouseInventory","salesWarehouseAge181365","salesWarehouseAge366Plus","totalPendingQc","totalPendingArrival"]);
export const columnsForCatalog = (canManageCatalogOrder:boolean) => canManageCatalogOrder ? ADMIN_COLUMNS : CUSTOMER_COLUMNS;
export const canEditCatalogColumn = (canManageCatalogOrder:boolean,key:ColumnKey) => canManageCatalogOrder ? !columnsByKey.get(key)?.readonly : key === "quantity";
export function columnLabel(column:{key:ColumnKey;label:string},salesWarehouseName="",labels?:Record<string,string>,priceRanges?:PriceRanges){
  if(priceRanges&&column.key==="price")return `U/P\n(1–${priceRanges.tier1Max}PCS)`;
  if(priceRanges&&column.key==="priceBulk")return `U/P\n(${priceRanges.tier1Max+1}–${priceRanges.tier2Max}PCS)`;
  const custom=labels?.[column.key]?.trim();
  if((column.key==="price"||column.key==="priceBulk")&&custom)return custom;
  const account=salesWarehouseName.trim()||"我的仓库";
  const warehouse=account.endsWith("仓库")?account:`${account}仓库`;
  if(column.key==="salesWarehouseInventory")return `${account}\n库存`;
  if(column.key==="salesWarehouseAge181365")return `${warehouse}\n181–365库龄`;
  if(column.key==="salesWarehouseAge366Plus")return `${warehouse}\n366天以上`;
  if(column.key==="totalPendingQc")return "总仓\n待质检";
  if(column.key==="totalPendingArrival")return "总仓\n待到货";
  return column.label;
}
export const layoutOf = (d:QuoteDraft):SheetLayout => d.layout || {widths:{},heights:{},hidden:[...(!d.showBrand?["brand"]:[]),...(!d.showCategory?["category"]:[]),...(!d.showPrice?["price","priceBulk","msrp","amount"]:[])],freeze:true};
const customerColumnKeys = new Set<string>(CUSTOMER_COLUMNS.map(column=>column.key));
export const defaultCustomerLayout = (d:QuoteDraft):SheetLayout => {
  const layout=layoutOf(d);
  return {...layout,hidden:layout.hidden.filter(key=>!customerColumnKeys.has(key))};
};
export type Point={r:number;c:number};
export type CellRange={start:Point;end:Point};
export function bounds(range:CellRange){return {r0:Math.min(range.start.r,range.end.r),r1:Math.max(range.start.r,range.end.r),c0:Math.min(range.start.c,range.end.c),c1:Math.max(range.start.c,range.end.c)};}
export function defaultAmountFormula(row:number,columns:WorkbookColumn[]=COLUMNS,priceRanges:PriceRanges=DEFAULT_PRICE_RANGES){
  const letter=(key:ColumnKey)=>columnLetter(columns.findIndex(column=>column.key===key));
  const quantity=letter("quantity"),price=letter("price"),bulk=letter("priceBulk");
  return `=IF(${quantity}${row}="","",IF(${quantity}${row}<=${priceRanges.tier1Max},IF(${price}${row}="","",ROUND(${price}${row}*${quantity}${row},2)),IF(${quantity}${row}<=${priceRanges.tier2Max},IF(${bulk}${row}="","",ROUND(${bulk}${row}*${quantity}${row},2)),"")))`;
}
export function rowPositions(products:MaterialProduct[]){return new Map(products.map((p,i)=>[p.sku,i+3]));}
export function rawValue(d:QuoteDraft,p:MaterialProduct,key:ColumnKey,row:number,positions?:Map<string,number>,columns:WorkbookColumn[]=COLUMNS):string {
  const l=d.lines[p.sku];
  if(key==="photo")return l?.photoData || p.assets[0]?.thumbnailUrl || "";
  if(key==="sku")return p.sku;
  if(key==="chineseName")return p.chineseName || "";
  if(key==="listingDate")return p.listingDate || "";
  if(key==="inventory"&&typeof p.availableInventory==="number")return String(p.availableInventory);
  if(key==="salesWarehouseInventory"&&typeof p.salesWarehouseInventory==="number")return String(p.salesWarehouseInventory);
  if(key==="salesWarehouseAge181365"&&typeof p.salesWarehouseAge181365==="number")return String(p.salesWarehouseAge181365);
  if(key==="salesWarehouseAge366Plus"&&typeof p.salesWarehouseAge366Plus==="number")return String(p.salesWarehouseAge366Plus);
  if(key==="totalPendingQc"&&typeof p.totalPendingQc==="number")return String(p.totalPendingQc);
  if(key==="totalPendingArrival"&&typeof p.totalPendingArrival==="number")return String(p.totalPendingArrival);
  if(key==="amount"){
    if(l?.formula===undefined)return defaultAmountFormula(row,columns,priceRangesOf(d));
    if(positions&&l.formulaRows)return l.formula.split(/("(?:[^"]|"")*")/).map((part,i)=>i%2?part:part.replace(/(\$?[A-Z]+)(\$?)(\d+)/gi,(_,col,absolute,refRow)=>{const sku=l.formulaRows?.[refRow],target=sku?positions.get(sku):undefined;return target?`${col}${absolute}${target}`:"#REF!";})).join("");
    return shiftFormula(l.formula,row-(l.formulaRow||row));
  }
  if(key==="name"||key==="brand"||key==="category")return l?.edited?.includes(key) ? l[key]||"" : l?.[key] || p[key];
  return String(l?.[key as keyof QuoteLine] || "");
}
export function createCalculator(d:QuoteDraft,products:MaterialProduct[],columns:WorkbookColumn[]=COLUMNS){
  const positions=rowPositions(products);
  const cache=new Map<string,FormulaValue>(),visiting=new Set<string>();
  const read=(ref:string):FormulaValue=>{const a=parseAddress(ref);if(!a||a.row<3||a.row>products.length+2||a.col>=columns.length)return "#REF!";return cell(a.row-3,columns[a.col].key);};
  const cell=(r:number,key:ColumnKey):FormulaValue=>{
    if(!products[r])return "#REF!";const id=`${r}:${key}`;if(cache.has(id))return cache.get(id)!;if(visiting.has(id))return "#CIRC!";
    const raw=rawValue(d,products[r],key,r+3,positions,columns);let value:FormulaValue=raw;
    if(key==="amount"&&raw.startsWith("=")){visiting.add(id);value=evaluateFormula(raw,read);visiting.delete(id);}
    else if(COLUMNS.find(c=>c.key===key)?.numeric&&raw!=="")value=Number(raw);
    cache.set(id,value);return value;
  };
  return {cell,read,raw:(r:number,key:ColumnKey)=>products[r]?rawValue(d,products[r],key,r+3,positions,columns):""};
}
export function sheetTotals(d:QuoteDraft,products:MaterialProduct[]){const calc=createCalculator(d,products);let quantity=0,amountCents=0,unpriced=0;products.forEach((p,r)=>{const qty=Number(d.lines[p.sku]?.quantity)||0;quantity+=qty;const v=calc.cell(r,"amount");if(typeof v==="number")amountCents+=Math.round(v*100);else if(qty)unpriced++;});return {quantity,amountCents,unpriced};}
export function normalizeCell(key:ColumnKey,value:string):string {
  if(key==="amount"){if(value==="")return "";if(!value.startsWith("=")){const number=value.trim().replace(/[$€£¥,]/g,"");if(/^-?\d{1,12}(\.\d{1,2})?$/.test(number))return "="+number;throw Error("Enter a number or an amount formula beginning with =.");}if(value.length>5000)throw Error("Formula is too long.");return expandFormulaRanges(value);}
  if(["price","priceBulk","msrp"].includes(key)){const v=value.trim().replace(/[$€£¥,]/g,"");if(!/^\d{0,7}(\.\d{0,2})?$/.test(v))throw Error("Prices must be non-negative numbers with up to two decimal places.");return v.replace(/\.$/,"");}
  if(key==="quantity"||key==="inventory"){const v=value.trim().replace(/,/g,"");if(!new RegExp(`^\\d{0,${key==="quantity"?6:8}}$`).test(v))throw Error("Quantities and inventory must be non-negative whole numbers.");return v;}
  return value.slice(0,160);
}
export function inventoryLimit(d:QuoteDraft,p:MaterialProduct):number|null {
  if(typeof p.availableInventory==="number"&&Number.isInteger(p.availableInventory)&&p.availableInventory>=0)return p.availableInventory;
  const fallback=d.lines[p.sku]?.inventory;
  return typeof fallback==="string"&&/^\d{1,8}$/.test(fallback)?Number(fallback):null;
}
export type CellChange={sku:string;key:ColumnKey;value:string;row:number};
export function applyCellChanges(d:QuoteDraft,changes:CellChange[],products:MaterialProduct[]=[],enforceInventory=false):QuoteDraft {
  const normalized=changes.filter(c=>!COLUMNS.find(col=>col.key===c.key)?.readonly).map(c=>({...c,value:normalizeCell(c.key,c.value)}));
  if(enforceInventory){const bySku=new Map(products.map(product=>[product.sku,product]));for(const change of normalized){if(change.key!=="quantity"||change.value==="")continue;const product=bySku.get(change.sku),limit=product?inventoryLimit(d,product):null;if(limit===null)throw Error(`Inventory is unavailable for SKU ${change.sku}. Refresh the catalog and try again.`);if(Number(change.value)>limit)throw Error(`SKU ${change.sku}: order quantity cannot exceed inventory (${limit.toLocaleString()}).`);}}
  const lines={...d.lines},order=new Set(d.order);
  for(const c of normalized){const key=c.key==="amount"?"formula":c.key;const line={...(lines[c.sku]||emptyLine())};Object.assign(line,{[key]:c.value,edited:[...new Set([...(line.edited||[]),key])]});if(key==="formula"){
    line.formulaRow=c.row;line.formulaRows={};
    for(const [i,part] of c.value.split(/("(?:[^"]|"")*")/).entries())if(i%2===0)for(const ref of part.matchAll(/\$?[A-Z]+\$?(\d+)/gi)){const r=Number(ref[1]),sku=r===c.row?c.sku:products[r-3]?.sku;if(sku)line.formulaRows[String(r)]=sku;}
  }if(c.key==="quantity"&&Number(c.value)>0)order.add(c.sku);lines[c.sku]=line;}
  // A workbook may contain more rows; PDF export offers a smaller selected set.
  return {...d,lines,order:[...order]};
}
export function toTSV(matrix:string[][]){return matrix.map(row=>row.map(v=>/[\t\n\r"]/.test(v)?`"${v.replace(/"/g,'""')}"`:v).join("\t")).join("\n");}
export function fromTSV(text:string):string[][]{
  if(text.length>2_000_000)throw Error("Paste a smaller cell range.");const rows:string[][]=[[]];let value="",quoted=false;
  const push=()=>{rows[rows.length-1].push(value);value="";};
  for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){value+='"';i++;}else if(quoted||!value)quoted=!quoted;else value+=c;}else if(!quoted&&(c==='\t'||c==='\r'||c==='\n')){push();if(c!=='\t'){if(c==='\r'&&text[i+1]==='\n')i++;rows.push([]);}}else value+=c;}
  if(quoted)throw Error("Unclosed quoted cell in clipboard data.");push();if(rows.length>1&&rows.at(-1)?.length===1&&rows.at(-1)?.[0]==="")rows.pop();return rows;
}
export function rangeAddress(range:CellRange,visible:ColumnKey[],columns:WorkbookColumn[]=COLUMNS){const b=bounds(range),address=(r:number,c:number)=>columnLetter(columns.findIndex(x=>x.key===visible[c]))+(r+3);const a=address(b.r0,b.c0),z=address(b.r1,b.c1);return a===z?a:`${a}:${z}`;}
export function fillChanges(d:QuoteDraft,rows:MaterialProduct[],visible:ColumnKey[],source:CellRange,target:CellRange,columns:WorkbookColumn[]=COLUMNS):CellChange[]{
  const positions=rowPositions(rows);
  const a=bounds(source),b=bounds(target),changes:CellChange[]=[];
  for(let r=b.r0;r<=b.r1;r++)for(let c=b.c0;c<=b.c1;c++){if(r>=a.r0&&r<=a.r1&&c>=a.c0&&c<=a.c1)continue;const sr=a.r0+((r-a.r0)%(a.r1-a.r0+1)+(a.r1-a.r0+1))%(a.r1-a.r0+1),sc=a.c0+((c-a.c0)%(a.c1-a.c0+1)+(a.c1-a.c0+1))%(a.c1-a.c0+1);const key=visible[c];if(!rows[r]||!rows[sr]||!key)continue;let value=rawValue(d,rows[sr],visible[sc],sr+3,positions,columns);
    if(value.startsWith("=")&&key==="amount")value=shiftFormula(value,r-sr,columns.findIndex(x=>x.key===key)-columns.findIndex(x=>x.key===visible[sc]));
    else if(["quantity","price","priceBulk","msrp","inventory"].includes(key)&&a.r1>a.r0){const start=rawValue(d,rows[a.r0],visible[sc],a.r0+3),end=rawValue(d,rows[a.r1],visible[sc],a.r1+3);if(start!==""&&end!==""&&Number.isFinite(Number(start))&&Number.isFinite(Number(end)))value=String(Math.round((Number(start)+(Number(end)-Number(start))/(a.r1-a.r0)*(r-a.r0))*100)/100);}
    changes.push({sku:rows[r].sku,key,value,row:r+3});}
  return changes;
}
