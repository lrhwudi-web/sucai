import { PDFDocument, StandardFonts, rgb, type PDFFont, type PDFPage } from "pdf-lib";
import type { QuoteDraft } from "./quotation";
import type { MaterialProduct } from "../types";
import { COLUMNS, layoutOf, rawValue, type ColumnKey } from "./workbookData.ts";
export interface PdfOptions { images: Map<string, Uint8Array>; fontBytes?: Uint8Array }
const ink=rgb(0,0,0),white=rgb(1,1,1),blue=rgb(.714,.776,.898),muted=rgb(.4,.43,.45);
const W=841.89,H=595.28,M=26;
function wrap(value: string, font: PDFFont, size: number, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of value.replace(/[\r\n\t]+/g, " ").split(/(\s+)/)) {
    if (font.widthOfTextAtSize(line + word, size) <= width) { line += word; continue; }
    if (line.trim()) { lines.push(line.trim()); line = ""; }
    for (const char of word) {
      if (font.widthOfTextAtSize(line + char, size) > width && line) { lines.push(line.trim()); line = ""; }
      line += char;
    }
  }
  if (line.trim()) lines.push(line.trim());
  return lines.length ? lines : [""];
}

export async function createQuotationPdf(draft:QuoteDraft,products:MaterialProduct[],options:PdfOptions){
  if(!products.length)throw Error("Select products before exporting.");
  const pdf=await PDFDocument.create();pdf.setTitle(draft.title);if(draft.company)pdf.setAuthor(draft.company);pdf.setSubject("Product catalog with fillable quantities and notes");
  const regular=await pdf.embedFont(StandardFonts.Helvetica),bold=await pdf.embedFont(StandardFonts.HelveticaBold);let font=regular;
  if(options.fontBytes){const {default:fontkit}=await import("@pdf-lib/fontkit");pdf.registerFontkit(fontkit);font=await pdf.embedFont(options.fontBytes,{subset:false});}
  const form=pdf.getForm(),layout=layoutOf(draft);
  // Amounts recalculate in the workbook and Excel. PDF collects the customer's quantities.
  const columns=COLUMNS.filter(c=>c.key!=="amount"&&(["sku","quantity","note"].includes(c.key)||!layout.hidden.includes(c.key)));
  const totalWidth=columns.reduce((n,c)=>n+(layout.widths[c.key]||c.width),0),scale=(W-2*M)/totalWidth;
  const widths=columns.map(c=>(layout.widths[c.key]||c.width)*scale);
  const draw=(page:PDFPage,text:string,x:number,y:number,size=8,f=font,color=ink)=>page.drawText(text,{x,y,size,font:f,color});
  const field=(page:PDFPage,name:string,x:number,y:number,w:number,h:number,text:string,qty=false)=>{const f=form.createTextField(name);f.setMaxLength(qty?6:160);f.setText(text);f.addToPage(page,{x,y,width:w,height:h,font,borderWidth:.4,borderColor:qty?rgb(.44,.62,.79):rgb(.82,.84,.87),backgroundColor:qty?rgb(.92,.96,1):white,textColor:ink});f.setFontSize(qty?10:8);return f;};
  let page:PDFPage,y=0;
  const addPage=(first:boolean)=>{page=pdf.addPage([W,H]);
    const info=[draft.company,draft.contact,draft.reference?`Ref: ${draft.reference}`:""].filter(Boolean).join("  |  ");
    if(info)draw(page,info,M,H-20,Math.min(8,(W-2*M)/Math.max(1,font.widthOfTextAtSize(info,1))),font,muted);
    y=H-33;page.drawRectangle({x:M,y:y-43,width:W-2*M,height:43,borderWidth:.9,borderColor:ink,color:white});
    const title=draft.title||"Craftsman Golf Accessories Catalog",titleFont=options.fontBytes?font:bold,size=Math.min(25,(W-2*M-24)/titleFont.widthOfTextAtSize(title,1));draw(page,title,(W-titleFont.widthOfTextAtSize(title,size))/2,y-29,size,titleFont);y-=43;
    if(first){draw(page,"Buyer / company",M,y-14,7,regular,muted);field(page,"buyer_company",M+82,y-21,236,18,"");draw(page,"Order reference / date",M+340,y-14,7,regular,muted);field(page,"buyer_order",M+441,y-21,218,18,"");y-=30;}
    let x=M;columns.forEach((c,i)=>{page.drawRectangle({x,y:y-32,width:widths[i],height:32,borderWidth:.5,borderColor:ink,color:blue});const labels=c.label.replaceAll("–","-").split("\n");labels.forEach((t,j)=>{const size=Math.min(8,(widths[i]-8)/bold.widthOfTextAtSize(t,1));draw(page,t,x+(widths[i]-bold.widthOfTextAtSize(t,size))/2,y-(labels.length===1?19:12+j*11),size,bold);});x+=widths[i];});y-=32;
  };
  addPage(true);
  for(let index=0;index<products.length;index++){
    const p=products[index],row=index+3,size=8;
    const textLines=columns.map((c,i)=>wrap(rawValue(draft,p,c.key,row),font,size,widths[i]-8));
    const rowHeight=Math.min(350,Math.max(66,...textLines.map((lines,i)=>columns[i].key==="photo"||columns[i].key==="note"?66:lines.length*10+12)));
    if(y-rowHeight<40)addPage(false);let x=M;
    for(let c=0;c<columns.length;c++){const col=columns[c],w=widths[c],value=rawValue(draft,p,col.key,row);page!.drawRectangle({x,y:y-rowHeight,width:w,height:rowHeight,borderWidth:.5,borderColor:ink,color:white});
      if(col.key==="photo"){const bytes=options.images.get(p.sku);if(bytes){const image=bytes[0]===0x89?await pdf.embedPng(bytes):await pdf.embedJpg(bytes),dim=image.scaleToFit(w-8,rowHeight-10);page!.drawImage(image,{x:x+(w-dim.width)/2,y:y-rowHeight+(rowHeight-dim.height)/2,...dim});}}
      else if(["quantity","note","price","priceBulk"].includes(col.key)){const h=col.key==="note"?Math.min(rowHeight-12,40):22;const f=field(page!,`item_${index}_${col.key}`,x+4,y-rowHeight/2-h/2,w-8,h,value,col.key==="quantity");if(col.key==="note"){f.enableMultiline();f.setFontSize(8);}}
      else{const lines=textLines[c],lineHeight=Math.min(10,(rowHeight-12)/lines.length),fontSize=Math.min(size,lineHeight*.8);const start=y-(rowHeight-lines.length*lineHeight)/2-fontSize;lines.forEach((line,j)=>draw(page!,line,["name","category"].includes(col.key)?x+4:x+(w-font.widthOfTextAtSize(line,fontSize))/2,start-j*lineHeight,fontSize));}x+=w;
    }y-=rowHeight;
  }
  const pages=pdf.getPages();pages.forEach((p,i)=>{draw(p,`Fill quantities and notes, then save and return this PDF.  |  ${products.length} products  |  ${draft.currency}`,M,23,7,regular,muted);draw(p,`${i+1} / ${pages.length}`,W-M-34,23,7,regular,muted);});form.updateFieldAppearances(font);return pdf.save();
}
