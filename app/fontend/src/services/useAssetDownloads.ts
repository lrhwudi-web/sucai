import { useEffect, useRef, useState } from "react";
import type { MaterialProduct } from "../types";
import { loadProductDetail } from "./materials";
import { AssetDownloadQueue, downloadIsActive, type AssetDownloadJob, type DownloadDirectory } from "./assetDownloads";

type PickerWindow = Window & { showDirectoryPicker?: (options: { id: string; mode: "readwrite" }) => Promise<DownloadDirectory> };

export function useAssetDownloads(account: number | undefined, notify: (message: string) => void) {
  const [manager] = useState(() => new AssetDownloadQueue(loadProductDetail));
  const [jobs, setJobs] = useState<AssetDownloadJob[]>([]);
  const [choosingFolder, setChoosingFolder] = useState(false);
  const root = useRef<DownloadDirectory | null>(null);
  const accountRef = useRef(account);
  accountRef.current = account;
  const pickerBusy = useRef(false);
  const hasActive = jobs.some(downloadIsActive);

  useEffect(() => manager.subscribe(setJobs), [manager]);
  useEffect(() => {
    manager.clear(); root.current = null;
    return () => { manager.clear(); root.current = null; };
  }, [account, manager]);
  useEffect(() => {
    if (!hasActive) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [hasActive]);

  const selectFolder = async () => {
    const picker = (window as PickerWindow).showDirectoryPicker;
    if (!picker) return null;
    // Called directly by the click handler, before any network request consumes user activation.
    return picker.call(window, { id: "kairay-assets", mode: "readwrite" });
  };
  const add = async (products: MaterialProduct[]) => {
    if (!account || !products.length || pickerBusy.current) return;
    const newProducts = products.filter((product) => !manager.snapshot().some((job) => job.sku === product.sku));
    if (!newProducts.length) { notify("These products are already in Downloads. Use Retry or remove a finished task to download again."); return; }
    const requestedAccount = account;
    pickerBusy.current = true; setChoosingFolder(true);
    try {
      const selected = root.current || await selectFolder();
      if (requestedAccount !== accountRef.current) return;
      root.current = selected;
      manager.add(newProducts, root.current);
    } catch (error) {
      if (error instanceof Error && ["NotAllowedError", "SecurityError", "NotSupportedError"].includes(error.name)) {
        if (requestedAccount !== accountRef.current) return;
        manager.add(newProducts, null);
        notify("Folder saving is unavailable in this browser. Individual download links are ready below.");
      } else if (!(error instanceof Error && error.name === "AbortError")) notify(error instanceof Error ? error.message : "The destination folder could not be selected. Use Individual file links instead.");
    } finally { pickerBusy.current = false; setChoosingFolder(false); }
  };
  const showLinks = (products: MaterialProduct[]) => {
    if (!account || pickerBusy.current) return;
    manager.add(products, null);
  };
  const retry = (sku: string) => manager.retry(sku);
  const chooseAgain = async (sku: string) => {
    const requestedAccount = account;
    try {
      const selected = await selectFolder();
      if (requestedAccount !== accountRef.current) return;
      root.current = selected;
      manager.retry(sku, selected);
    } catch (error) { if (!(error instanceof Error && error.name === "AbortError")) notify("Choose a writable folder, then retry."); }
  };
  return { jobs, add, showLinks, retry, chooseAgain, choosingFolder, hasActive, folder: root.current?.name, cancel: (sku: string) => manager.cancel(sku), remove: (sku: string) => manager.remove(sku) };
}
