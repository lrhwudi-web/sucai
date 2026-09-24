import { useCallback, useEffect, useState } from "react";
import { emptyDraft, mergeManagedCatalog, sanitizeDraft, type QuoteDraft } from "./quotation";

export function useQuotation(account: string) {
  const key = account ? `kairay.quotation.v1:${account}` : "";
  const [state, setState] = useState<{ key: string; draft: QuoteDraft; past: QuoteDraft[]; future: QuoteDraft[] }>({ key: "", draft: emptyDraft(), past: [], future: [] });
  const [storageFailed, setStorageFailed] = useState(false);
  useEffect(() => {
    let draft = emptyDraft();
    try { if (key) draft = sanitizeDraft(JSON.parse(localStorage.getItem(key) || "null")); setStorageFailed(false); }
    catch { setStorageFailed(true); }
    setState({ key, draft, past: [], future: [] });
  }, [key]);
  useEffect(() => {
    if (!key || state.key !== key) return;
    try { localStorage.setItem(key, JSON.stringify(state.draft)); setStorageFailed(false); }
    catch { setStorageFailed(true); }
  }, [key, state]);
  const update = useCallback((fn: (draft: QuoteDraft) => QuoteDraft) => {
    setState((current) => {
      if (current.key !== key) return current;
      const draft = fn(current.draft);
      if (draft === current.draft || JSON.stringify(draft) === JSON.stringify(current.draft)) return current;
      return { key, draft, past: [...current.past, current.draft].slice(-60), future: [] };
    });
  }, [key]);
  const undo = useCallback(() => setState((s) => s.key === key && s.past.length ? { ...s, draft: s.past[s.past.length-1], past: s.past.slice(0,-1), future: [s.draft,...s.future] } : s), [key]);
  const redo = useCallback(() => setState((s) => s.key === key && s.future.length ? { ...s, draft: s.future[0], past: [...s.past,s.draft], future: s.future.slice(1) } : s), [key]);
  const applyManagedTemplate = useCallback((template: QuoteDraft, templateKey: string, customer: boolean) => {
    if (!key || !templateKey) return;
    const revisionKey = `${key}:catalog-revision`;
    try { if (localStorage.getItem(revisionKey) === templateKey) return; } catch { /* apply the server version */ }
    setState(current => current.key === key ? { key, draft: customer ? mergeManagedCatalog(template,current.draft) : sanitizeDraft(template), past: [], future: [] } : current);
    try { localStorage.setItem(revisionKey,templateKey); } catch { setStorageFailed(true); }
  }, [key]);
  return { draft: state.key === key ? state.draft : emptyDraft(), update, undo, redo, applyManagedTemplate, canUndo: state.key === key && state.past.length > 0, canRedo: state.key === key && state.future.length > 0, storageFailed, ready: state.key === key && Boolean(key) };
}
