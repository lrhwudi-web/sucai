import type { MaterialProduct } from "../types";
import type { QuoteDraft } from "./quotation";
import { loadProductDetail, SessionExpiredError } from "../services/materials";
import { thumbnailVariantUrl } from "../utils/thumbnails";
export async function compactPicture(blob:Blob):Promise<string>{
  const bitmap=await createImageBitmap(blob);const scale=Math.min(1,360/Math.max(bitmap.width,bitmap.height));const canvas=document.createElement("canvas");canvas.width=canvas.height=Math.max(1,Math.round(Math.max(bitmap.width,bitmap.height)*scale));const ctx=canvas.getContext("2d");if(!ctx)throw Error("Image conversion unavailable.");ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,(canvas.width-bitmap.width*scale)/2,(canvas.height-bitmap.height*scale)/2,bitmap.width*scale,bitmap.height*scale);bitmap.close();return canvas.toDataURL("image/jpeg",.82);
}
export async function preparePictures(draft:QuoteDraft,products:MaterialProduct[],onProgress:(s:string)=>void){
  const photos=new Map<string,string>();let next=0,done=0;
  await Promise.all(Array.from({length:Math.min(4,products.length)},async()=>{while(next<products.length){const p=products[next++];let detail:MaterialProduct;try{detail=await loadProductDetail(p.sku);}catch(e){throw e instanceof SessionExpiredError?e:Error(`Could not verify product ${p.sku}. Reload and retry.`);}
    const override=draft.lines[p.sku]?.photoData;if(override)photos.set(p.sku,override);else{const asset=detail.assets.find(a=>a.kind==="image"&&!a.internalOnly&&!/(^|[\\/])(_internal|内部|源文件)([\\/]|$)/i.test(a.path||""));if(asset)try{const response=await fetch(thumbnailVariantUrl(asset.thumbnailUrl,"drawer"),{credentials:"include",signal:AbortSignal.timeout(20000)});if(response.status===401)throw new SessionExpiredError("Your session expired. Sign in again.");if(response.ok)photos.set(p.sku,await compactPicture(await response.blob()));}catch(e){if(e instanceof SessionExpiredError)throw e;}}
    onProgress(`Preparing pictures ${++done}/${products.length}`);
  }}));return photos;
}
export function downloadBytes(bytes:Uint8Array,name:string,mime:string){const url=URL.createObjectURL(new Blob([new Uint8Array(bytes)],{type:mime}));const link=document.createElement("a");link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();return {url,name,size:bytes.length};}
