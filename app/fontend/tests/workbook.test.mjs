import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import ExcelJS from 'exceljs';
import JSZip from 'jszip';
import {emptyDraft,priceRangesOf,sanitizeDraft} from '../src/quotation/quotation.ts';
import {applyCellChanges,fillChanges,fromTSV,toTSV,createCalculator,rawValue,sheetTotals,COLUMNS,ADMIN_COLUMNS,CUSTOMER_COLUMNS,canEditCatalogColumn,columnLabel,defaultCustomerLayout} from '../src/quotation/workbookData.ts';
import {evaluateFormula,shiftFormula} from '../src/quotation/formulas.ts';
import {buildCatalogXlsx,readCatalogXlsx,stripEmbeddedWorkbookPictures} from '../src/quotation/excelCatalog.ts';
import {assertExcelImportSize,EXCEL_IMPORT_TOO_LARGE_MESSAGE,MAX_EXCEL_IMPORT_BYTES} from '../src/quotation/excelImportPolicy.ts';
const products=['5902160','5902211','7203131','7203132'].map(sku=>({sku,name:`Golf accessory ${sku}`,brand:'Craftsman Golf',category:'Accessories',assets:[],otherCategory:""}));

test('administrator and customer worksheets expose the correct columns',()=>{
 const admin=ADMIN_COLUMNS.map(column=>column.key),customer=CUSTOMER_COLUMNS.map(column=>column.key);
 assert.equal(admin.includes('quantity'),false);assert.equal(admin.includes('amount'),false);
 assert.equal(admin.includes('chineseName'),true);assert.equal(admin.includes('listingDate'),true);
 assert.equal(customer.includes('quantity'),true);assert.equal(customer.includes('amount'),true);
 for(const key of ['salesWarehouseInventory','salesWarehouseAge181365','salesWarehouseAge366Plus','totalPendingQc','totalPendingArrival'])assert.equal(customer.includes(key),false);
 assert.equal(canEditCatalogColumn(false,'quantity'),true);
 for(const key of customer.filter(key=>key!=='quantity'))assert.equal(canEditCatalogColumn(false,key),false);
 assert.equal(canEditCatalogColumn(true,'note'),true);
});
test('customer workbooks open every customer column by default',()=>{
 const draft={...emptyDraft(),layout:{widths:{},heights:{},hidden:['brand','quantity','amount','listingDate'],freeze:true}};
 const layout=defaultCustomerLayout(draft);
 for(const column of CUSTOMER_COLUMNS)assert.equal(layout.hidden.includes(column.key),false,column.key);
 assert.equal(layout.hidden.includes('listingDate'),true);
});
const edit=(r,key,value)=>({sku:products[r].sku,key,value,row:r+3});
test('password-protected Excel imports show a clear localized error',async()=>{
 const encryptedOfficeFile=new Uint8Array([0xD0,0xCF,0x11,0xE0,0xA1,0xB1,0x1A,0xE1,0,0,0,0]);
 await assert.rejects(
  readCatalogXlsx(encryptedOfficeFile,products),
  error=>error instanceof Error&&error.message==='该 Excel 已加密，请解除打开密码后重新上传。',
 );
});
test('Excel uploads allow 80 MB and reject larger files before reading their contents',()=>{
 assert.doesNotThrow(()=>assertExcelImportSize(MAX_EXCEL_IMPORT_BYTES));
 assert.throws(()=>assertExcelImportSize(MAX_EXCEL_IMPORT_BYTES+1),error=>error instanceof Error&&error.message===EXCEL_IMPORT_TOO_LARGE_MESSAGE);
});
test('formula references follow SKUs through sorting and fail visibly when a referenced row is excluded',()=>{
 let d=applyCellChanges(emptyDraft(),[edit(0,'price','2'),edit(1,'price','4'),edit(2,'price','8'),edit(3,'price','16'),edit(0,'quantity','10'),edit(0,'amount','=SUM(F3:F5)*K3')],products);
 assert.equal(createCalculator(d,products).cell(0,'amount'),140);
 const shuffled=[products[2],products[0],products[3],products[1]];
 assert.equal(createCalculator(sanitizeDraft(d),shuffled).cell(1,'amount'),140);
 assert.equal(createCalculator(d,[products[0]]).cell(0,'amount'),'#REF!');
 d=applyCellChanges(d,[edit(0,'amount','=$F$4*K3')],products);
 assert.equal(createCalculator(d,shuffled).cell(1,'amount'),40);
});
test('tier amounts respect boundaries, blanks, zero prices and circular formulas',()=>{
 let d=applyCellChanges(emptyDraft(),[edit(0,'price','6.90'),edit(0,'priceBulk','6.20'),edit(0,'quantity','29')]);
 assert.equal(createCalculator(d,products).cell(0,'amount'),200.1);
 for(const [qty,result] of [['30',186],['50',310],['51',''],['','']]){d=applyCellChanges(d,[edit(0,'quantity',qty)]);assert.equal(createCalculator(d,products).cell(0,'amount'),result);}
 d=applyCellChanges(d,[edit(0,'quantity','3'),edit(0,'price','0')]);assert.equal(createCalculator(d,products).cell(0,'amount'),0);
 d=applyCellChanges(d,[edit(0,'amount','=L3')]);assert.equal(createCalculator(d,products).cell(0,'amount'),'#CIRC!');
 assert.equal(sheetTotals(d,products).unpriced,1);
});
test('administrator price ranges change headings and price boundaries',()=>{
 let d=sanitizeDraft({...emptyDraft(),layout:{widths:{},heights:{},hidden:[],freeze:true,priceRanges:{tier1Max:49,tier2Max:99}}});
 assert.deepEqual(priceRangesOf(d),{tier1Max:49,tier2Max:99});
 assert.equal(columnLabel(COLUMNS.find(column=>column.key==='price'),'','',d.layout.priceRanges),'U/P\n(1–49PCS)');
 assert.equal(columnLabel(COLUMNS.find(column=>column.key==='priceBulk'),'','',d.layout.priceRanges),'U/P\n(50–99PCS)');
 d=applyCellChanges(d,[edit(0,'price','6.90'),edit(0,'priceBulk','6.20'),edit(0,'quantity','49')]);
 assert.equal(createCalculator(d,products).cell(0,'amount'),338.1);
 for(const [qty,result] of [['50',310],['99',613.8],['100','']]){d=applyCellChanges(d,[edit(0,'quantity',qty)]);assert.equal(createCalculator(d,products).cell(0,'amount'),result);}
 const invalid=sanitizeDraft({...emptyDraft(),layout:{widths:{},heights:{},hidden:[],freeze:true,priceRanges:{tier1Max:50,tier2Max:50}}});
 assert.deepEqual(priceRangesOf(invalid),{tier1Max:29,tier2Max:50});
});
test('range paste is atomic, preserves readonly SKU, and deletion survives reload',()=>{
 const d=emptyDraft();assert.throws(()=>applyCellChanges(d,[edit(0,'quantity','10'),edit(1,'quantity','bad')]));assert.deepEqual(d.lines,{});
 const next=applyCellChanges(d,[edit(0,'name',''),edit(0,'sku','wrong'),edit(0,'quantity','12'),edit(1,'note','Blue\nLogo')]);
 assert.equal(rawValue(sanitizeDraft(next),products[0],'name',3),'');assert.equal(rawValue(next,products[0],'sku',3),products[0].sku);
 assert.deepEqual(next.order,[products[0].sku]);assert.equal(d.lines[products[0].sku],undefined);
 const pastedAmount=applyCellChanges(next,[edit(0,'amount','1,250.50')]);assert.equal(createCalculator(pastedAmount,products).cell(0,'amount'),1250.5);
 const matrix=[['12','Blue\nLogo','A "quote"'],['0','Tabs\there','']];assert.deepEqual(fromTSV(toTSV(matrix)),matrix);
});
test('live available inventory takes precedence over an imported fallback, including zero stock',()=>{
 const d=applyCellChanges(emptyDraft(),[edit(0,'inventory','145'),edit(1,'inventory','46')]);
 assert.equal(rawValue(d,{...products[0],availableInventory:146},'inventory',3),'146');
 assert.equal(rawValue(d,{...products[1],availableInventory:0},'inventory',4),'0');
 assert.equal(rawValue(d,products[0],'inventory',3),'145');
});
test('customer quantity edits cannot exceed displayed inventory',()=>{
 const live=[{...products[0],availableInventory:5},{...products[1],availableInventory:0}];
 const d=applyCellChanges(emptyDraft(),[edit(0,'quantity','5')],live,true);
 assert.equal(d.lines[products[0].sku].quantity,'5');
 assert.throws(()=>applyCellChanges(d,[edit(0,'quantity','6')],live,true),/cannot exceed inventory \(5\)/);
 assert.throws(()=>applyCellChanges(d,[edit(1,'quantity','1')],live,true),/cannot exceed inventory \(0\)/);
 assert.throws(()=>applyCellChanges(d,[edit(2,'quantity','1')],products,true),/Inventory is unavailable/);
});
test('drag fill extends a number series and shifts relative formula references',()=>{
 const keys=COLUMNS.map(c=>c.key);let d=applyCellChanges(emptyDraft(),[edit(0,'quantity','10'),edit(1,'quantity','20')]);
 d=applyCellChanges(d,fillChanges(d,products,keys,{start:{r:0,c:10},end:{r:1,c:10}},{start:{r:0,c:10},end:{r:3,c:10}}));
 assert.deepEqual(products.map(p=>d.lines[p.sku].quantity),['10','20','30','40']);
 d=applyCellChanges(d,[edit(0,'amount','=ROUND($F3*K3,2)')]);d=applyCellChanges(d,fillChanges(d,products,keys,{start:{r:0,c:11},end:{r:0,c:11}},{start:{r:0,c:11},end:{r:2,c:11}}));
 assert.equal(rawValue(d,products[2],'amount',5),'=ROUND($F5*K5,2)');
 assert.equal(shiftFormula('=SUM($F3,F$3,$F$3)+IF(A3="F3",0,1)',2,1),'=SUM($F5,G$3,$F$3)+IF(B5="F3",0,1)');
});
test('formula evaluator supports ranges and reports invalid references without evaluating code',()=>{
 assert.equal(evaluateFormula('=SUM(A3:A5)+ROUND(0.1*3,2)',r=>({A3:1,A4:2,A5:3}[r]??'#REF!')),6.3);
 assert.equal(evaluateFormula('=1/0',()=>0),'#DIV/0!');assert.equal(evaluateFormula('=window.alert(1)',()=>0),'#NAME?');
 assert.equal(evaluateFormula('=ROUND(-1.235,2)',()=>0),-1.24);
 assert.equal(evaluateFormula('=SUM(A3:ZZZZ3)',()=>1),'#VALUE!');assert.equal(evaluateFormula('=IF(1=1,2,1/0)',()=>0),2);
});
test('Excel round-trip exports photos but imports only cells, formulas and layout',async()=>{
 let d=applyCellChanges(emptyDraft(),[edit(0,'price','6.90'),edit(0,'priceBulk','6.20'),edit(0,'quantity','30'),edit(0,'note','NEW'),edit(1,'name','=Not a formula')]);
 d.layout={widths:{name:250},heights:{[products[0].sku]:110},hidden:['inventory'],freeze:true,labels:{price:'U/P (1-49PCS)',priceBulk:'U/P (50-99PCS)'}};
 const photo='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRt8AAAAASUVORK5CYII=';
 const exportProducts=products.map((product,index)=>index===0?{...product,availableInventory:146,salesWarehouseName:'黄彩丽',salesWarehouseInventory:8,salesWarehouseAge181365:3,salesWarehouseAge366Plus:5,totalPendingQc:2,totalPendingArrival:1}:product);
 const bytes=await buildCatalogXlsx(d,exportProducts,new Map([[products[0].sku,photo]]),undefined,{centerNote:true});
 const book=new ExcelJS.Workbook();await book.xlsx.load(bytes);const sheet=book.worksheets[0];
 assert.equal(sheet.getCell('B3').value,products[0].sku);assert.equal(sheet.getCell('F2').value,'U/P (1-49PCS)');assert.equal(sheet.getCell('G2').value,'U/P (50-99PCS)');assert.equal(sheet.getCell('F3').value,6.9);assert.equal(sheet.getCell('J3').value,146);assert.equal(sheet.getCell('L3').value.result,186);
 assert.equal(sheet.getCell('M2').value,'黄彩丽\n库存');assert.equal(sheet.getCell('N2').value,'黄彩丽仓库\n181-365库龄');assert.equal(sheet.getCell('Q2').value,'总仓\n待到货');
 assert.deepEqual(['M3','N3','O3','P3','Q3'].map(address=>sheet.getCell(address).value),[8,3,5,2,1]);
 assert.equal(sheet.pageSetup.printArea,`A1:S${products.length+2}`);
 assert.equal(sheet.getCell('C4').value,'=Not a formula');assert.equal(sheet.getImages().length,1);assert.equal(sheet.views[0].xSplit||0,0);assert.equal(sheet.views[0].ySplit,2);assert.equal(sheet.getCell('I3').alignment.horizontal,'center');assert.equal(sheet.getCell('I3').alignment.vertical,'middle');assert.equal(sheet.getColumn(10).hidden,true);
 const stripped=await stripEmbeddedWorkbookPictures(bytes);const strippedZip=await JSZip.loadAsync(stripped);
 assert.equal(Object.keys(strippedZip.files).some(name=>/^xl\/(?:media|drawings)\//i.test(name)),false,'picture payloads must be removed before ExcelJS loads the workbook');
 const strippedBook=new ExcelJS.Workbook();await strippedBook.xlsx.load(stripped);
 assert.equal(strippedBook.worksheets[0].getImages().length,0,'the temporary workbook passed to ExcelJS must not contain drawing relationships');
 const imported=await readCatalogXlsx(bytes,products);assert.equal(imported.matched,4);assert.equal(imported.photos.length,0,'embedded workbook pictures must be discarded before ExcelJS parses the catalog');
 assert.deepEqual(imported.skuOrder,products.map(product=>product.sku));
 assert.equal(imported.currency,'USD');assert.equal(imported.layout.freeze,false);assert.equal(imported.layout.labels,undefined);
 const restored=applyCellChanges(emptyDraft(),imported.changes);assert.equal(createCalculator(restored,products).cell(0,'amount'),186);assert.equal(restored.lines[products[0].sku].note,'NEW');
 await mkdir('tests/output',{recursive:true});await writeFile('tests/output/workbook-roundtrip.xlsx',bytes);
});
test('Excel import reports distinct missing SKUs separately from duplicate rows',async()=>{
 const book=new ExcelJS.Workbook(),sheet=book.addWorksheet('Import');
 sheet.addRow(['SKU','Product Name','Quantity']);
 sheet.addRow([products[0].sku.toLowerCase(),'Known product',3]);
 sheet.addRow(['MISSING-900','Missing product',2]);
 sheet.addRow([products[0].sku,'Duplicate product',4]);
 const bytes=new Uint8Array(await book.xlsx.writeBuffer());
 const result=await readCatalogXlsx(bytes,products);
 assert.equal(result.searched,2);assert.equal(result.matched,1);assert.equal(result.duplicates,1);
 assert.deepEqual(result.missingSkus,['MISSING-900']);assert.equal(result.skipped,2);
 assert.deepEqual(result.skuOrder,[products[0].sku]);
 await mkdir('tests/output',{recursive:true});await writeFile('tests/output/workbook-missing-skus.xlsx',bytes);
});
test('price column labels are administrator-owned draft settings',()=>{
 const draft=sanitizeDraft({...emptyDraft(),layout:{widths:{},heights:{},hidden:[],freeze:true,labels:{price:'Dealer price',priceBulk:'Case price',inventory:'ignored'}}});
 assert.deepEqual(draft.layout.labels,{price:'Dealer price',priceBulk:'Case price'});
 assert.equal(columnLabel(COLUMNS.find(column=>column.key==='price'),'Warehouse',draft.layout.labels),'Dealer price');
 assert.equal(columnLabel(COLUMNS.find(column=>column.key==='priceBulk'),'Warehouse',draft.layout.labels),'Case price');
});
test('customer template imports all known rows without its embedded photos',{skip:!existsSync('D:/素材/Craftsman Golf Accessories Catalog 模板.xlsx')||!existsSync('tests/fixtures/catalogue/products.json')},async()=>{
 const all=JSON.parse(await readFile('tests/fixtures/catalogue/products.json','utf8'));
 const result=await readCatalogXlsx(new Uint8Array(await readFile('D:/素材/Craftsman Golf Accessories Catalog 模板.xlsx')),all);
 assert.equal(result.matched,131);assert.equal(result.photos.length,0);assert.ok(result.changes.some(c=>c.key==='inventory'&&c.value!==''));
 assert.equal(result.skuOrder[0],'5902160');assert.equal(new Set(result.skuOrder).size,131);
 assert.ok(!result.changes.some(c=>c.key==='price'&&c.value!==''),'blank source prices must stay blank');
 await writeFile('tests/output/import-summary.json',JSON.stringify({matched:result.matched,photos:result.photos.length,skipped:result.skipped,title:result.title,warnings:result.warnings,first:result.changes.slice(0,12)},null,2));
});
