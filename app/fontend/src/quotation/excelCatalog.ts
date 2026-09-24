import ExcelJS from "exceljs";
import JSZip from "jszip";
import type { MaterialProduct } from "../types";
import type { QuoteDraft, QuoteLine, SheetLayout } from "./quotation";
import { COLUMNS, columnLabel, createCalculator, layoutOf, normalizeCell, rawValue, type CellChange, type ColumnKey, type WorkbookColumn } from "./workbookData.ts";
import { columnIndex, columnLetter, expandFormulaRanges } from "./formulas.ts";

const COMPOUND_FILE_SIGNATURE=[0xD0,0xCF,0x11,0xE0,0xA1,0xB1,0x1A,0xE1];
const ENCRYPTED_EXCEL_MESSAGE="该 Excel 已加密，请解除打开密码后重新上传。";

function isPasswordProtectedOfficeFile(bytes:Uint8Array){
  return bytes.length>=COMPOUND_FILE_SIGNATURE.length&&COMPOUND_FILE_SIGNATURE.every((value,index)=>bytes[index]===value);
}

function isWorkbookPictureEntry(name:string){
  const normalized=name.replace(/^\//,"");
  return /^xl\/(?:media|drawings)\//i.test(normalized)||/^xl\/cellimages\.xml$/i.test(normalized);
}
function removePictureRelationships(xml:string){
  return xml.replace(/<(?:\w+:)?Relationship\b[^>]*\/>/gi,relationship=>{
    const type=relationship.match(/\bType=["']([^"']+)["']/i)?.[1]||"";
    const target=relationship.match(/\bTarget=["']([^"']+)["']/i)?.[1]||"";
    return /\/(?:drawing|image)$/i.test(type)||/(?:^|\/)\.\.\/(?:media|drawings)\//i.test(target)||/(?:^|\/)(?:media|drawings)\//i.test(target)?"":relationship;
  });
}

export async function stripEmbeddedWorkbookPictures(bytes:Uint8Array){
  const zip=await JSZip.loadAsync(bytes);let changed=false;
  for(const name of Object.keys(zip.files))if(isWorkbookPictureEntry(name)){zip.remove(name);changed=true;}
  for(const name of Object.keys(zip.files)){
    const entry=zip.file(name);if(!entry)continue;
    if(/^xl\/worksheets\/sheet\d+\.xml$/i.test(name.replace(/^\//,""))){
      const xml=await entry.async("string");
      const next=xml.replace(/<(?:\w+:)?(?:drawing|picture)\b[^>]*\/>/gi,"");
      if(next!==xml){zip.file(name,next);changed=true;}
    }else if(/\.rels$/i.test(name)){
      const xml=await entry.async("string"),next=removePictureRelationships(xml);
      if(next!==xml){zip.file(name,next);changed=true;}
    }
  }
  if(!changed)return bytes;
  return zip.generateAsync({type:"uint8array",compression:"DEFLATE",compressionOptions:{level:1}});
}

export interface CatalogXlsxOptions { centerNote?: boolean }

export async function buildCatalogXlsx(draft:QuoteDraft,products:MaterialProduct[],photos:Map<string,string>=new Map(),columns:WorkbookColumn[]=COLUMNS,options:CatalogXlsxOptions={}){
  const book=new ExcelJS.Workbook();book.creator=draft.company||"Craftsman Golf";book.calcProperties.fullCalcOnLoad=true;
  book.title=draft.title;book.subject=draft.reference;
  const contactDetails=[draft.company,draft.contact,draft.reference?`Ref: ${draft.reference}`:""].filter(Boolean).join("\n");
  book.description=contactDetails;
  const layout=layoutOf(draft),sheet=book.addWorksheet("Product Catalog",{views:[{state:"frozen",ySplit:2,showGridLines:true}]});
  const salesWarehouseName=products.find(product=>product.salesWarehouseName)?.salesWarehouseName||"";
  sheet.columns=columns.map(c=>({key:c.key,width:(layout.widths[c.key]||c.width)/7,hidden:layout.hidden.includes(c.key)}));
  sheet.mergeCells(1,1,1,columns.length);const title=sheet.getCell(1,1);title.value=draft.title||"Craftsman Golf Accessories Catalog";title.font={name:"Arial",size:24,bold:true};title.alignment={vertical:"middle",horizontal:"center"};sheet.getRow(1).height=40;
  if(contactDetails)title.note=contactDetails;
  sheet.getRow(2).values=columns.map(c=>columnLabel(c,salesWarehouseName,layout.labels,layout.priceRanges).replace("–","-"));sheet.getRow(2).height=38;
  const calc=createCalculator(draft,products,columns);
  products.forEach((p,index)=>{const row=index+3;sheet.getRow(row).height=(layout.heights[p.sku]||86)*.75;
    columns.forEach((col,c)=>{const cell=sheet.getCell(row,c+1),raw=calc.raw(index,col.key);cell.font={name:"Arial",size:10};const leftAligned=["name","chineseName","category"].includes(col.key)||(col.key==="note"&&!options.centerNote);cell.alignment={vertical:"middle",horizontal:leftAligned?"left":"center",wrapText:true};
      cell.border={top:{style:"thin",color:{argb:"FF333333"}},bottom:{style:"thin",color:{argb:"FF333333"}},left:{style:"thin",color:{argb:"FF333333"}},right:{style:"thin",color:{argb:"FF333333"}}};
      if(col.key==="photo"){const photo=photos.get(p.sku)||draft.lines[p.sku]?.photoData;if(photo){const id=book.addImage({base64:photo,extension:photo.startsWith("data:image/png")?"png":"jpeg"});const side=Math.min((layout.widths.photo||110)-12,(layout.heights[p.sku]||86)-10);sheet.addImage(id,{tl:{col:c+.08,row:row-1+.06},ext:{width:side,height:side}});}return;}
      if(col.key==="amount"&&raw.startsWith("=")){const result=calc.cell(index,"amount");cell.value={formula:raw.slice(1),result:typeof result==="string"&&result.startsWith("#")?{error:(result==="#CIRC!"?"#REF!":result) as ExcelJS.CellErrorValue["error"]}:result};}
      else cell.value=col.numeric&&raw!==""?Number(raw):raw;
      if(["price","priceBulk","msrp","amount"].includes(col.key))cell.numFmt=`"${draft.currency} "#,##0.00`;
      else if(col.numeric)cell.numFmt="#,##0";else if(col.key==="sku")cell.numFmt="@";
    });
  });
  sheet.getRow(2).eachCell(cell=>{cell.font={name:"Arial",size:10,bold:true};cell.fill={type:"pattern",pattern:"solid",fgColor:{argb:"FFB6C6E5"}};cell.alignment={horizontal:"center",vertical:"middle",wrapText:true};cell.border={top:{style:"thin"},bottom:{style:"thin"},left:{style:"thin"},right:{style:"thin"}};});
  sheet.autoFilter={from:{row:2,column:1},to:{row:Math.max(2,products.length+2),column:columns.length}};
  sheet.pageSetup={paperSize:9,orientation:"landscape",fitToPage:true,fitToWidth:1,fitToHeight:0,printTitlesRow:"1:2",printArea:`A1:${columnLetter(columns.length-1)}${products.length+2}`};
  sheet.headerFooter.oddFooter="&L"+(draft.company||"")+"&RPage &P of &N";
  return new Uint8Array(await book.xlsx.writeBuffer());
}
function cellText(value:ExcelJS.CellValue):string {
  if(value===null||value===undefined)return "";
  if(typeof value!=="object")return String(value);
  if("richText" in value)return value.richText.map(t=>t.text).join("");
  if("formula" in value||"sharedFormula" in value)return cellText(value.result as ExcelJS.CellValue);
  if("text" in value)return String(value.text);
  return "";
}
function headerKey(value:string):ColumnKey|null{
  const v=value.toUpperCase().replace(/[\s_()（）\-–—/.,]/g,"");
  if(["SKU","ITEMNO","ARTICLENO","货号","产品编号"].includes(v))return "sku";
  if(["BRAND","品牌"].includes(v))return "brand";
  if(["中文品名","中文名称","CHINESENAME"].includes(v))return "chineseName";
  if(["ITEM","NAME","PRODUCTNAME","品名","产品名称"].includes(v))return "name";
  if(["CATEGORY","类别","分类"].includes(v))return "category";
  if(["PHOTO","PICTURE","IMAGE","图片"].includes(v))return "photo";
  if(v.startsWith("UP")&&v.includes("3050")||v==="BULKPRICE")return "priceBulk";
  if(v.startsWith("UP")&&v.includes("129")||["UNITPRICE","PRICE","单价"].includes(v))return "price";
  if(v==="MSRP"||v==="建议零售价")return "msrp";
  if(["LISTINGDATE","LISTDATE","上架日期","刊登日期"].includes(v))return "listingDate";
  if(["NOTE","NOTES","REMARKS","备注"].includes(v))return "note";
  if(["INVENTORY","STOCK","库存","本地总库存"].includes(v))return "inventory";
  if(["ORDERQTY","QTY","QUANTITY","下单数量","数量"].includes(v))return "quantity";
  if(["AMOUNT","TOTAL","金额"].includes(v))return "amount";
  if(v.includes("181365")&&v.includes("库龄"))return "salesWarehouseAge181365";
  if((v.includes("366天以上")||v.includes("365天以上"))&&v.includes("仓库"))return "salesWarehouseAge366Plus";
  if(v==="总仓待质检")return "totalPendingQc";
  if(v==="总仓待到货")return "totalPendingArrival";
  if(v.endsWith("库存")&&v!=="库存")return "salesWarehouseInventory";
  return null;
}
function isTierPriceHeader(value:string){const v=value.toUpperCase().replace(/[\s_()（）\-–—/.,]/g,"");return v.startsWith("UP")&&/\d/.test(v);}
export interface ExcelImportResult { changes:CellChange[]; photos:{sku:string;bytes:Uint8Array;mime:string}[]; skuOrder:string[]; missingSkus:string[]; searched:number; duplicates:number; layout:SheetLayout; title:string; currency?:string; matched:number; skipped:number; warnings:string[] }
export async function readCatalogXlsx(bytes:Uint8Array,products:MaterialProduct[]):Promise<ExcelImportResult>{
  if(isPasswordProtectedOfficeFile(bytes))throw Error(ENCRYPTED_EXCEL_MESSAGE);
  const cellOnlyBytes=await stripEmbeddedWorkbookPictures(bytes);
  const book=new ExcelJS.Workbook();await book.xlsx.load(cellOnlyBytes as unknown as Parameters<typeof book.xlsx.load>[0],{ignoreNodes:["drawing","picture"]});
  const allowed=new Map(products.map((p,i)=>[p.sku.trim().toUpperCase(),{sku:p.sku,row:i+3}]));
  let sheet:ExcelJS.Worksheet|undefined,headerRow=0,mapping=new Map<number,ColumnKey>();
  for(const ws of book.worksheets){for(let r=1;r<=Math.min(30,ws.rowCount);r++){const map=new Map<number,ColumnKey>();ws.getRow(r).eachCell((c,i)=>{const label=cellText(c.value);let k=headerKey(label);if(!k&&isTierPriceHeader(label))k=!([...map.values()].includes("price"))?"price":!([...map.values()].includes("priceBulk"))?"priceBulk":null;if(k)map.set(i,k);});if([...map.values()].includes("sku")&&map.size>=3){sheet=ws;headerRow=r;mapping=map;break;}}if(sheet)break;}
  if(!sheet)throw Error("No product table found. Include a SKU column and labeled catalog columns.");
  const changes:CellChange[]=[],photos:ExcelImportResult["photos"]=[],warnings:string[]=[],rows=new Map<number,string>(),seen=new Set<string>(),missingSkus:string[]=[];let skipped=0,duplicates=0;
  const skuCol=[...mapping].find(([,k])=>k==="sku")![0];
  if(sheet.rowCount>10000)throw Error("Import up to 10,000 product rows at a time.");
  for(let r=headerRow+1;r<=sheet.rowCount;r++){const rawSku=cellText(sheet.getCell(r,skuCol).value).trim();if(!rawSku)continue;const normalizedSku=rawSku.toUpperCase();if(seen.has(normalizedSku)){skipped++;duplicates++;continue;}seen.add(normalizedSku);const product=allowed.get(normalizedSku);if(!product){skipped++;missingSkus.push(normalizedSku);continue;}rows.set(r,product.sku);}
  for(const [r,sku] of rows)for(const [c,key] of mapping){if(key==="photo"||key==="sku")continue;const cell=sheet.getCell(r,c);let value=cellText(cell.value);
    if(key==="amount"){if(cell.type!==ExcelJS.ValueType.Formula)continue;value=expandFormulaRanges("="+cell.formula);value=value.split(/("(?:[^"]|"")*")/).map((part,i)=>i%2?part:part.replace(/(\$?)([A-Z]+)(\$?)(\d+)/gi,(_,ca,col,ra,row)=>{const destKey=mapping.get(columnIndex(col)+1),destSku=rows.get(Number(row));if(!destKey||!destSku)return "#REF!";return `${ca}${columnLetter(COLUMNS.findIndex(x=>x.key===destKey))}${ra}${allowed.get(destSku.toUpperCase())!.row}`;})).join("");}
    try{value=normalizeCell(key,value);changes.push({sku,key,value,row:allowed.get(sku.toUpperCase())!.row});}catch{warnings.push(`${sku}: invalid ${key} was left unchanged.`);}
  }
  const layout:SheetLayout={widths:{},heights:{},hidden:[],freeze:sheet.views?.length?sheet.views.some(v=>v.state==="frozen"&&(v.xSplit||0)>0):true};for(const [c,key] of mapping){layout.widths[key]=Math.max(55,Math.min(600,(sheet.getColumn(c).width||12)*7));if(sheet.getColumn(c).hidden)layout.hidden.push(key);}
  for(const [r,sku] of rows)layout.heights[sku]=Math.max(32,Math.min(300,(sheet.getRow(r).height||64)*4/3));
  const title=headerRow>1?cellText(sheet.getCell(1,1).value).slice(0,120):"";
  const priceColumn=[...mapping].find(([,key])=>key==="price")?.[0];
  const currency=priceColumn?sheet.getCell(headerRow+1,priceColumn).numFmt?.match(/"(USD|EUR|GBP|CAD|AUD|CNY|JPY)\s*"/)?.[1]:undefined;
  return {changes,photos,skuOrder:[...rows.values()],missingSkus,searched:seen.size,duplicates,layout,title,currency,matched:rows.size,skipped,warnings};
}
