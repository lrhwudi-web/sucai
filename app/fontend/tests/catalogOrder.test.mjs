import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {arrangeProducts,catalogDraftFingerprint,completeCatalogOrder,groupCatalogProducts,moveCatalogProduct,publishableCatalogDraft} from '../src/quotation/catalogOrder.ts';
import {emptyDraft,mergeManagedCatalog} from '../src/quotation/quotation.ts';

test('successful customer order is announced near the top of the confirmation dialog',async()=>{
 const source=await readFile(new URL('../src/quotation/QuoteBuilder.tsx',import.meta.url),'utf8');
 const successNotice=source.indexOf('className="quote-order-success"');
 const orderDetails=source.indexOf('className="quote-details-grid"');
 assert.ok(successNotice>0,'customer order success notice is missing');
 assert.ok(orderDetails>successNotice,'customer order success notice must appear before the order details and preview');
 assert.ok(!source.includes('readyOrder && <div className="wb-download"'),'customer order success must not use the narrow bottom download strip');
});

test('salesperson SKU order is stable and unknown products append in API order',()=>{
 const products=['A','B','C','D'].map(sku=>({sku}));
 assert.deepEqual(arrangeProducts(products,['C','A','MISSING']).map(p=>p.sku),['C','A','B','D']);
 assert.strictEqual(arrangeProducts(products,[]),products);
 assert.deepEqual(completeCatalogOrder([products[2],products[0]],products),['C','A','B','D']);
});

test('salesperson can group products and then manually refine the saved row order',()=>{
 const products=[
  {sku:'3',brand:'B',category:'Putter',themes:['Ocean'],setCode:'SET-2'},
  {sku:'1',brand:'A',category:'Glove',themes:['Lucky'],setCode:'SET-1'},
  {sku:'2',brand:'A',category:'Glove',themes:['Lucky'],setCode:'SET-1'},
  {sku:'4',brand:'B',category:'Putter',themes:[],setCode:''},
 ];
 assert.deepEqual(groupCatalogProducts(products,'category').map(p=>p.sku),['1','2','3','4']);
 assert.deepEqual(groupCatalogProducts(products,'series').map(p=>p.sku),['1','2','3','4']);
 assert.deepEqual(groupCatalogProducts(products,'set').map(p=>p.sku),['1','2','3','4']);
 assert.deepEqual(moveCatalogProduct(products,'3',2).map(p=>p.sku),['1','2','3','4']);
 assert.strictEqual(moveCatalogProduct(products,'missing',1),products);
});

test('published table keeps prices and layout but excludes private quote fields and embedded pictures',()=>{
 const draft={...emptyDraft(),company:'Private customer',contact:'buyer@example.com',reference:'Q-1',order:['A'],layout:{widths:{name:240},heights:{A:90},hidden:['msrp'],freeze:true},lines:{A:{name:'Custom',price:'6.90',priceBulk:'6.20',quantity:'12',note:'NEW',formula:'=F3*K3',formulaRow:3,formulaRows:{3:'A'},photoData:'data:image/png;base64,AAAA',edited:['name','price']}}};
 const published=publishableCatalogDraft(draft);
 assert.equal(published.lines.A.price,'6.90');assert.equal(published.lines.A.note,'NEW');assert.equal(published.lines.A.quantity,'');
 assert.equal(published.lines.A.formula,undefined);assert.equal(published.lines.A.photoData,undefined);
 assert.deepEqual(published.order,[]);assert.equal(published.company,'');assert.deepEqual(published.layout,draft.layout);
});

test('unpublished-change fingerprint ignores customer-private quote fields',()=>{
 const baseline=emptyDraft();
 const privateOnly={...baseline,company:'Buyer',contact:'Pat',reference:'PO-1',order:['A'],lines:{A:{name:'',price:'',quantity:'12',note:'',formula:'=F3*K3',edited:['quantity','formula'],photoData:'data:image/png;base64,AAAA'}}};
 assert.equal(catalogDraftFingerprint(privateOnly),catalogDraftFingerprint(baseline));
 assert.notEqual(catalogDraftFingerprint({...baseline,title:'Sales A table'}),catalogDraftFingerprint(baseline));
 assert.notEqual(catalogDraftFingerprint({...baseline,lines:{A:{name:'',price:'6.90',quantity:'',note:'',edited:['price']}}}),catalogDraftFingerprint(baseline));
});

test('customer receives manager table changes while retaining quantity, selection and quote identity',()=>{
 const manager={...emptyDraft(),title:'Sales A catalog',currency:'EUR',layout:{widths:{name:230},heights:{},hidden:['msrp'],freeze:true},lines:{A:{name:'Manager name',price:'5.50',quantity:'',note:'NEW',edited:['name']}}};
 const personal={...emptyDraft(),company:'Buyer Co',contact:'Pat',reference:'PO-9',order:['A'],lines:{A:{name:'Old name',price:'4',quantity:'25',note:'Old',formula:'=F3*K3'}}};
 const merged=mergeManagedCatalog(manager,personal);
 assert.equal(merged.title,'Sales A catalog');assert.equal(merged.currency,'EUR');assert.equal(merged.lines.A.name,'Manager name');assert.equal(merged.lines.A.price,'5.50');
 assert.equal(merged.lines.A.quantity,'25');assert.equal(merged.lines.A.formula,'=F3*K3');assert.deepEqual(merged.order,['A']);assert.equal(merged.company,'Buyer Co');assert.equal(merged.reference,'PO-9');
});
