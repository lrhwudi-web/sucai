import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {visibleGalleryImages} from '../src/quotation/galleryImages.ts';

const asset=(id,kind='image',internalOnly=false)=>({id,name:id,kind,mimeType:kind==='image'?'image/jpeg':'video/mp4',thumbnailUrl:`/thumb/${id}`,previewUrl:`/media/${id}`,downloadUrl:`/download/${id}`,internalOnly});
const product={sku:'5902160',name:'Scorecard Holder',brand:'Craftsman Golf',category:'Accessories',otherCategory:'',material:'',batch:'',permission:'public',owner:'',updatedAt:'',drivePath:'',themes:[],assets:[asset('cover'),asset('alternate'),asset('video','video'),asset('private','image',true)]};

test('photo gallery shows imported and every customer-visible product image without mutating product data',()=>{
 const before=structuredClone(product);
 const images=visibleGalleryImages(product,'data:image/jpeg;base64,AA==');
 assert.deepEqual(images.map(image=>image.id),['catalog-photo-5902160','cover','alternate']);
 assert.deepEqual(product,before);
});

test('photo gallery excludes empty, duplicate, non-image and internal assets',()=>{
 const duplicate={...asset('cover'),previewUrl:'/media/second-copy'};
 const empty={...asset('empty'),thumbnailUrl:'',previewUrl:''};
 assert.deepEqual(visibleGalleryImages({...product,assets:[...product.assets,duplicate,empty]}).map(image=>image.id),['cover','alternate']);
});

test('original preview covers and blurs the catalog product drawer',()=>{
 const appStyles=readFileSync(new URL('../src/styles.css',import.meta.url),'utf8');
 const catalogStyles=readFileSync(new URL('../src/quotation/catalogSheet.css',import.meta.url),'utf8');
 const original=appStyles.match(/\.original-modal-backdrop\s*\{[\s\S]*?z-index:\s*(\d+);[\s\S]*?backdrop-filter:\s*blur\(([^)]+)\)/);
 const drawer=catalogStyles.match(/\.wb-drawer-layer\s*\{[\s\S]*?z-index:\s*(\d+);/);
 assert.ok(original,'original preview needs a backdrop z-index and blur');
 assert.ok(drawer,'catalog product drawer needs an explicit z-index');
 assert.ok(Number(original[1])>Number(drawer[1]),`original preview z-index ${original[1]} must exceed drawer z-index ${drawer[1]}`);
 assert.notEqual(original[2],'0px');
});
