import type { MaterialProduct } from "../types";
import type { QuoteDraft } from "./quotation";
import { createQuotationPdf } from "./quotationPdf";
import { COLUMNS, layoutOf, rawValue } from "./workbookData";
import { preparePictures, downloadBytes } from "./workbookMedia";
export async function downloadQuotation(draft:QuoteDraft,products:MaterialProduct[],onProgress:(s:string)=>void){
  const photos=await preparePictures(draft,products,onProgress),images=new Map<string,Uint8Array>();
  for(const [sku,data] of photos)images.set(sku,Uint8Array.from(atob(data.split(",")[1]),c=>c.charCodeAt(0)));
  const hidden=layoutOf(draft).hidden;
  const text=[draft.title,draft.company,draft.contact,draft.reference,...products.flatMap((p,r)=>COLUMNS.filter(c=>!["photo","amount"].includes(c.key)&&(!hidden.includes(c.key)||["quantity","note","sku"].includes(c.key))).map(c=>rawValue(draft,p,c.key,r+3)))].join("");
  let fontBytes:Uint8Array|undefined;
  if(/[^\x20-\x7e\r\n\t]/.test(text)){onProgress("Preparing document fonts…");const res=await fetch("/fonts/NotoSansSC-Regular.ttf",{signal:AbortSignal.timeout(60000)});if(!res.ok)throw Error("The document font could not be loaded. Please try again.");fontBytes=new Uint8Array(await res.arrayBuffer());}
  onProgress("Creating fillable PDF…");const bytes=await createQuotationPdf(draft,products,{images,fontBytes});const download=downloadBytes(bytes,`${(draft.reference||"Craftsman_Golf_Catalog").replace(/[^a-zA-Z0-9_-]/g,"_").slice(0,70)}.pdf`,"application/pdf");return {missingImages:products.length-images.size,...download};
}
