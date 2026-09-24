export const MAX_EXCEL_IMPORT_BYTES=80*1024*1024;
export const EXCEL_IMPORT_TOO_LARGE_MESSAGE="Excel 文件不能超过 80 MB，请删除内嵌图片或其他不必要内容后重新上传。";

export function assertExcelImportSize(size:number){
  if(size>MAX_EXCEL_IMPORT_BYTES)throw Error(EXCEL_IMPORT_TOO_LARGE_MESSAGE);
}
