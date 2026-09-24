import { useEffect, useMemo, useState } from "react";
import { ArrowUUpLeft, Check, CaretRight, Folder, FolderOpen, Plus, SpinnerGap } from "@phosphor-icons/react";
import { createDriveFolder, listDriveFolders } from "./adminService";

interface DriveFolderPickerProps {
  value: string;
  folders: string[];
  onChange: (path: string) => void;
  onFoldersChange: (folders: string[]) => void;
  onNotify: (message: string) => void;
}

const productBrandFolders = [
  "01 Craftsman Golf",
  "02 My Tag",
  "03 Big Crazy",
  "04 Big Teeth",
  "05 Caesar",
];

const productCategoryFolders = [
  "01 Headcover Set",
  "02 Plush Cover",
  "03 Driver Cover",
  "04 Fairway Cover",
  "05 Hybrid Cover",
  "06 Blade Putter Cover",
  "07 Mallet Putter Cover",
  "08 Square Mallet Putter Cover",
  "09 Iron Cover Set",
  "10 Wedge Cover Set",
  "11 Alignment Stick Cover",
  "12 Ball Marker & Divot Tool",
  "13 Scorecard Holder",
  "14 Golf Pouch",
  "15 Golf Towl",
  "16 Glove Caddie",
  "17 Golf Ball Pouch",
  "18 Range Finder Case",
  "Golf Accessories",
];

const brandedProductFolders = productBrandFolders.flatMap((brand) => productCategoryFolders.map((category) => {
  const actualCategory = category === "02 Plush Cover" && ["04 Big Teeth", "05 Caesar"].includes(brand)
    ? "02 Plush Headcover"
    : category;
  return `04 Product Images/${brand}/${actualCategory}`;
}));

const noBrandProductFolders = productCategoryFolders.map((category) => `04 Product Images (No Brand)/${category}`);

export const defaultDriveFolderLeaves = [
  "01 Product Catalogs",
  "02 Brand Assets",
  "03 Packaging Assets",
  ...brandedProductFolders,
  ...noBrandProductFolders,
  "05 Influencer Assets",
  "06 Show & Exhibitions/Thailand Golf Expo 2026",
  "06 Show & Exhibitions/China Golf Show 2026",
  "07 Event & Sponsorships/Indonesia/Payakumbuh Golf Tournament",
  "07 Event & Sponsorships/Thailand/Junior Golf Series",
  "08 Collection Assets",
];

export function expandFolderPaths(paths: string[]) {
  const expanded = new Set<string>();
  paths.forEach((path) => {
    const parts = normalizePath(path).split("/").filter(Boolean);
    parts.forEach((_part, index) => expanded.add(parts.slice(0, index + 1).join("/")));
  });
  return [...expanded];
}

function normalizePath(path: string) {
  return path.replaceAll("\\", "/").split("/").map((part) => part.trim()).filter(Boolean).join("/");
}

function parentPath(path: string) {
  const parts = normalizePath(path).split("/").filter(Boolean);
  return parts.slice(0, -1).join("/");
}

export function DriveFolderPicker({ value, folders, onChange, onFoldersChange, onNotify }: DriveFolderPickerProps) {
  const [open, setOpen] = useState(false);
  const [currentPath, setCurrentPath] = useState(normalizePath(value));
  const [adding, setAdding] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [loading, setLoading] = useState(false);

  const normalizedFolders = useMemo(() => expandFolderPaths(folders), [folders]);
  const children = useMemo(() => normalizedFolders
    .filter((path) => parentPath(path) === currentPath)
    .sort((a, b) => a.localeCompare(b, "en")), [currentPath, normalizedFolders]);
  const parts = currentPath.split("/").filter(Boolean);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    listDriveFolders(currentPath)
      .then((listing) => {
        if (!active || !listing) return;
        onFoldersChange(expandFolderPaths([...folders, ...listing.folders]));
        if (!listing.exact && listing.path !== currentPath) {
          setCurrentPath(listing.path);
          onNotify("建议目录在 Drive 中不存在，已返回最深的真实目录层级");
        }
      })
      .catch(() => onNotify("实时目录读取失败，已保留当前目录列表"))
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [currentPath, open]);

  const openBrowser = () => {
    setCurrentPath("");
    setAdding(false);
    setOpen((current) => !current);
  };

  const addFolder = async () => {
    const name = newFolderName.trim();
    if (!currentPath) {
      onNotify("请先选择一个一级目录，再新增下级目录");
      return;
    }
    if (!name || !/^[\x20-\x7E]+$/.test(name) || /[\\/]/.test(name)) {
      onNotify("Drive 文件夹名称需使用英文、数字或常用符号");
      return;
    }
    setLoading(true);
    try {
      const localPath = `${currentPath}/${name}`;
      const createdPath = normalizePath(await createDriveFolder(currentPath, name) || localPath);
      onFoldersChange(expandFolderPaths([...folders, createdPath]));
      setCurrentPath(createdPath);
      onChange(createdPath);
      setNewFolderName("");
      setAdding(false);
      onNotify(`已新增目录 ${name}`);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "目录创建失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="drive-folder-picker">
      <button type="button" className="folder-selected-value" onClick={openBrowser} aria-expanded={open}>
        <FolderOpen size={18} weight="duotone" />
        <span>{normalizePath(value) || "选择 Drive 目标目录"}</span>
        <strong>{open ? "收起" : "从 Drive 选择"}</strong>
      </button>

      {open && (
        <div className="folder-browser">
          <div className="folder-browser-heading">
            <div className="folder-breadcrumbs">
              <button type="button" onClick={() => setCurrentPath("")}>Google Drive 根目录</button>
              {parts.map((part, index) => (
                <span key={`${part}-${index}`}><CaretRight size={11} weight="bold" /><button type="button" onClick={() => setCurrentPath(parts.slice(0, index + 1).join("/"))}>{part}</button></span>
              ))}
            </div>
            {loading && <SpinnerGap className="is-spinning" size={17} weight="bold" />}
          </div>

          <div className="folder-browser-list">
            {currentPath && <button type="button" className="folder-up" onClick={() => setCurrentPath(parentPath(currentPath))}><ArrowUUpLeft size={17} weight="bold" /><span>返回上一级</span></button>}
            {children.map((path) => {
              const name = path.split("/").at(-1) || path;
              return <button type="button" className="folder-option" key={path} onClick={() => setCurrentPath(path)}><Folder size={19} weight="duotone" /><span>{name}</span><CaretRight size={14} weight="bold" /></button>;
            })}
            {!loading && !children.length && <div className="folder-browser-empty"><FolderOpen size={24} weight="duotone" /><span>当前 Drive 目录还没有下级文件夹</span></div>}
          </div>

          {adding ? (
            <div className="folder-create-row">
              <input autoFocus value={newFolderName} onChange={(event) => setNewFolderName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addFolder(); } }} placeholder="输入英文文件夹名称" />
              <button type="button" onClick={addFolder} disabled={loading}><Check size={15} weight="bold" /> 新增</button>
              <button type="button" onClick={() => { setAdding(false); setNewFolderName(""); }}>取消</button>
            </div>
          ) : (
            <div className="folder-browser-actions">
              <button type="button" onClick={() => setAdding(true)} disabled={!currentPath}><Plus size={16} weight="bold" /> 在此新增下级</button>
              <button type="button" className="is-primary" onClick={() => { if (currentPath) onChange(currentPath); setOpen(false); }} disabled={!currentPath}><Check size={16} weight="bold" /> 选择当前目录</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
