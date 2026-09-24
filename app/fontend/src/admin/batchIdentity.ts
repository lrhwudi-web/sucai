import type { PendingImport } from "./types";

type BatchFileIdentity = Pick<PendingImport, "name" | "driveName">;

export interface BatchIdentityValues {
  sku: string;
  englishName: string;
  driveName: string;
}

export function batchIdentityValidationError(values: BatchIdentityValues) {
  const sku = values.sku.trim();
  const englishName = values.englishName.trim();
  const driveName = values.driveName.trim();

  if (!sku) return "SKU 不能为空。";
  if (!englishName) return "英文品名不能为空。";
  if (!/^[\x20-\x7e]+$/.test(englishName)) return "英文品名只能使用英文字符，不能包含中文或特殊字符。";
  if (!/[A-Za-z]/.test(englishName)) return "英文品名必须包含英文字母，不能只填写数字。";
  if (!driveName) return "文件名不能为空。";
  if (!/^[\x20-\x7e]+$/.test(driveName)) return "文件名只能使用英文字符，不能包含中文或特殊字符。";
  if (/[\\/]/.test(driveName)) return "文件名不能包含 / 或 \\。";
  return "";
}

function splitFileName(value: string) {
  const dotIndex = value.lastIndexOf(".");
  return dotIndex > 0
    ? { stem: value.slice(0, dotIndex), extension: value.slice(dotIndex) }
    : { stem: value, extension: "" };
}

function productNameParts(stem: string, sku: string) {
  const cleanSku = sku.trim();
  const escapedSku = cleanSku.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (!cleanSku || !new RegExp(`^${escapedSku}(?:\\s|\\(|$)`, "i").test(stem)) return null;
  const sequence = stem.match(/(\s*\(\d+\))$/)?.[1] || "";
  const stemWithoutSequence = sequence ? stem.slice(0, -sequence.length) : stem;
  const separator = stemWithoutSequence.indexOf(" - ");
  const prefix = separator >= 0 ? stemWithoutSequence.slice(0, separator + 3) : `${cleanSku} `;
  return { prefix, productName: stemWithoutSequence.slice(prefix.length), sequence };
}

export function syncDriveNameWithEnglishName(
  driveName: string,
  sku: string,
  _previousEnglishName: string,
  englishName: string,
) {
  const nextName = englishName.trim();
  if (!driveName.trim() || !nextName) return driveName;
  const { stem, extension } = splitFileName(driveName.trim());
  const parts = productNameParts(stem, sku);
  if (!parts) return driveName;
  if (parts.productName.toLowerCase() === nextName.toLowerCase()) return driveName.trim();
  return `${parts.prefix}${nextName}${parts.sequence}${extension}`;
}

export function syncDriveFolderWithEnglishName(
  driveFolder: string,
  sku: string,
  _previousEnglishName: string,
  englishName: string,
) {
  const parts = driveFolder.replaceAll("\\", "/").split("/").filter(Boolean);
  const nextName = englishName.trim();
  if (!parts.length || !nextName) return driveFolder;
  const leaf = productNameParts(parts.at(-1) || "", sku);
  if (!leaf) return driveFolder;
  if (leaf.productName.toLowerCase() === nextName.toLowerCase()) return parts.join("/");
  parts[parts.length - 1] = `${leaf.prefix}${nextName}${leaf.sequence}`;
  return parts.join("/");
}

export function buildBatchDriveName(template: string, item: BatchFileIdentity, index: number, total: number) {
  const cleanTemplate = template.trim();
  if (total <= 1) return cleanTemplate;

  const templateParts = splitFileName(cleanTemplate);
  const currentParts = splitFileName(item.driveName || item.name);
  const sourceParts = splitFileName(item.name);
  const sourceSuffix = sourceParts.stem.match(/\s*(\(\d+\))\s*$/)?.[1];
  const currentSuffix = currentParts.stem.match(/\s*(\(\d+\))\s*$/)?.[1];
  const suffix = sourceSuffix || currentSuffix || `(${index + 1})`;
  const stem = templateParts.stem.replace(/\s*\(\d+\)\s*$/, "").trim();
  const extension = sourceParts.extension || currentParts.extension || templateParts.extension;
  return `${stem} ${suffix}${extension}`;
}
