import { useEffect, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import {
  ArrowSquareOut,
  ChatCircleText,
  Check,
  FilePdf,
  FolderOpen,
  Heart,
  ImageSquare,
  Info,
  LockKey,
  PaperPlaneTilt,
  SpinnerGap,
  Star,
  Tag,
  X,
} from "@phosphor-icons/react";
import { addProductMessage, loadMyProductMessages, recordOriginalOpen, type ProductMessage } from "../services/materials";
import type { MaterialAsset, MaterialProduct, ThemeOption } from "../types";
import { thumbnailVariantUrl } from "../utils/thumbnails";
import { AssetImage } from "./AssetImage";

interface ProductDrawerProps {
  product: MaterialProduct;
  onClose: () => void;
  onOpenDrive: () => void;
  onToggleFavorite: () => void;
  isAdmin: boolean;
  themeOptions: ThemeOption[];
  onSetCover: (asset: MaterialAsset) => Promise<void>;
  canSetCoverAsset?: (asset: MaterialAsset) => boolean;
  onSetThemes: (themes: string[]) => Promise<void>;
  onNotify: (message: string) => void;
  catalogPreview?: boolean;
}

function formatMessageTime(value: string): string {
  const date = new Date(value.endsWith("Z") ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

export function ProductDrawer({
  product,
  onClose,
  onOpenDrive,
  onToggleFavorite,
  isAdmin,
  themeOptions,
  onSetCover,
  canSetCoverAsset,
  onSetThemes,
  onNotify,
  catalogPreview = false,
}: ProductDrawerProps) {
  const [activeAsset, setActiveAsset] = useState(0);
  const [originalOpen, setOriginalOpen] = useState(false);
  const [messages, setMessages] = useState<ProductMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [coverSaving, setCoverSaving] = useState(false);
  const [themeDraft, setThemeDraft] = useState<string[]>([]);
  const [themesSaving, setThemesSaving] = useState(false);

  useEffect(() => {
    setActiveAsset(0);
    setOriginalOpen(false);
    setDraft("");
  }, [product.sku]);

  useEffect(() => {
    setThemeDraft(
      themeOptions
        .filter((option) => product.themes.includes(option.label))
        .map((option) => option.id),
    );
  }, [product.sku, product.themes, themeOptions]);

  useEffect(() => {
    if (catalogPreview) {
      setMessages([]);
      setMessagesLoading(false);
      return;
    }
    let mounted = true;
    setMessages([]);
    setMessagesLoading(true);
    loadMyProductMessages(product.sku)
      .then((result) => { if (mounted) setMessages(result); })
      .catch((error) => { if (mounted) onNotify(error instanceof Error ? error.message : "Your messages could not be loaded."); })
      .finally(() => { if (mounted) setMessagesLoading(false); });
    return () => { mounted = false; };
  }, [catalogPreview, onNotify, product.sku]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (originalOpen) setOriginalOpen(false);
      else onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, originalOpen]);

  const selectedAsset = product.assets[activeAsset] || product.assets[0];
  const canUpdateCover = Boolean(isAdmin && selectedAsset?.kind === "image" && (canSetCoverAsset?.(selectedAsset) ?? true));

  const openOriginal = () => {
    if (!selectedAsset) return;
    setOriginalOpen(true);
    void recordOriginalOpen(product.sku, selectedAsset.id).catch(() => undefined);
  };

  const submitMessage = async (event: FormEvent) => {
    event.preventDefault();
    const message = draft.trim();
    if (!message || submitting) return;
    setSubmitting(true);
    try {
      const created = await addProductMessage(product.sku, message);
      setMessages((current) => [created, ...current]);
      setDraft("");
      onNotify("Your message was sent to the admin team.");
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Your message could not be sent.");
    } finally {
      setSubmitting(false);
    }
  };

  const updateCover = async () => {
    if (!selectedAsset || selectedAsset.kind !== "image" || coverSaving || selectedAsset.id === product.coverId) return;
    setCoverSaving(true);
    try {
      await onSetCover(selectedAsset);
      setActiveAsset(0);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "The product cover could not be updated.");
    } finally {
      setCoverSaving(false);
    }
  };

  const updateThemes = async () => {
    if (themesSaving) return;
    setThemesSaving(true);
    try {
      await onSetThemes(themeDraft);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "The product themes could not be updated.");
    } finally {
      setThemesSaving(false);
    }
  };

  const originalModal = originalOpen && selectedAsset ? createPortal(
    <div className="original-modal-backdrop" role="presentation" onMouseDown={() => setOriginalOpen(false)}>
      <section
        className="original-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Original preview of ${selectedAsset.name}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span className="eyebrow">Original asset</span>
            <strong>{selectedAsset.name}</strong>
          </div>
          <button className="icon-button" onClick={() => setOriginalOpen(false)} aria-label="Close original preview">
            <X size={20} weight="bold" />
          </button>
        </header>
        <div className="original-modal-media">
          {selectedAsset.kind === "video" ? (
            <video
              src={selectedAsset.previewUrl}
              poster={thumbnailVariantUrl(selectedAsset.thumbnailUrl, "drawer")}
              controls
              autoPlay
              preload="metadata"
            />
          ) : selectedAsset.kind === "document" ? (
            <iframe src={selectedAsset.previewUrl} title={`PDF preview of ${selectedAsset.name}`} />
          ) : (
            <img src={selectedAsset.previewUrl} alt={selectedAsset.name} />
          )}
        </div>
      </section>
    </div>,
    document.body,
  ) : null;

  return (
    <>
    <aside className={`detail-drawer${catalogPreview ? " is-catalog-preview" : ""}`} aria-label={`${product.name} details`}>
      <div className="drawer-heading">
        <div>
          <span className="eyebrow">{product.sku}</span>
          <h2>{product.name}</h2>
          <p>{product.otherCategory ? `Other / ${product.otherCategory}` : `${product.brand} / ${product.category}`}</p>
        </div>
        <div className="drawer-heading-actions">
          {!catalogPreview && <button
            className={`icon-button drawer-favorite ${product.isFavorite ? "is-active" : ""}`}
            onClick={onToggleFavorite}
            aria-label={product.isFavorite ? "Remove from favorites" : "Add to favorites"}
            title={product.isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            <Heart size={20} weight={product.isFavorite ? "fill" : "bold"} />
          </button>}
          <button className="icon-button" onClick={onClose} aria-label="Close details">
            <X size={20} weight="bold" />
          </button>
        </div>
      </div>

      <div className="drawer-scroll">
        <div className="drawer-preview">
          {selectedAsset.kind === "video" ? (
            <video
              src={selectedAsset.previewUrl}
              poster={thumbnailVariantUrl(selectedAsset.thumbnailUrl, "drawer")}
              controls
              preload="none"
              aria-label={selectedAsset.name}
            />
          ) : selectedAsset.kind === "document" ? (
            <div className="document-preview">
              <FilePdf size={64} weight="duotone" />
              <strong>{selectedAsset.name}</strong>
              <button type="button" onClick={openOriginal}>Preview PDF</button>
            </div>
          ) : (
            <AssetImage
              src={thumbnailVariantUrl(selectedAsset.thumbnailUrl, "drawer")}
              alt={selectedAsset.name}
              loading="eager"
              fetchPriority="high"
            />
          )}
          {!catalogPreview && product.permission === "internal" ? (
            <span className="permission-badge internal">
              <LockKey size={13} weight="fill" />
              Internal access only
            </span>
          ) : null}
        </div>

        <div className="asset-filmstrip" aria-label="Asset preview list">
          {product.assets.map((asset, index) => (
            <button
              key={asset.id}
              className={index === activeAsset ? "filmstrip-item is-active" : "filmstrip-item"}
              onClick={() => setActiveAsset(index)}
              aria-label={`Preview ${asset.name}`}
            >
              {asset.kind === "document" ? (
                <div className="document-thumb"><FilePdf size={26} weight="duotone" /><small>PDF</small></div>
              ) : (
                <AssetImage
                  src={thumbnailVariantUrl(asset.thumbnailUrl, "small")}
                  alt=""
                  loading="lazy"
                  fetchPriority={index === activeAsset ? "high" : "low"}
                  fallbackLabel={`Preview ${index + 1} unavailable`}
                />
              )}
              {asset.id === product.coverId && <span className="filmstrip-cover-mark" title="Current cover"><Star size={10} weight="fill" /></span>}
              <span>{index + 1}</span>
            </button>
          ))}
        </div>

        <div className="drawer-section asset-summary">
          <div>
            <span>Current file</span>
            <strong>{selectedAsset.name}</strong>
          </div>
          {selectedAsset.kind === "document" ? <FilePdf size={22} weight="duotone" /> : <ImageSquare size={22} weight="duotone" />}
        </div>

        {canUpdateCover && (
          <button
            className={`drawer-cover-action ${selectedAsset.id === product.coverId ? "is-current" : ""}`}
            type="button"
            disabled={coverSaving || selectedAsset.id === product.coverId}
            onClick={updateCover}
          >
            {coverSaving ? <SpinnerGap className="is-spinning" size={17} weight="bold" /> : <Star size={17} weight={selectedAsset.id === product.coverId ? "fill" : "bold"} />}
            {selectedAsset.id === product.coverId ? "Current cover" : "Set current image as cover"}
          </button>
        )}

        {!catalogPreview && !product.otherCategory && (
          <section className="drawer-theme-section" aria-label="Product themes">
            <div className="drawer-theme-heading">
              <span><Tag size={17} weight="fill" /> Theme</span>
              <small>{isAdmin ? "Administrator-managed product themes" : "Product themes"}</small>
            </div>
            {isAdmin ? (
              <>
                <div className="drawer-theme-options">
                  {themeOptions.map((option) => {
                    const checked = themeDraft.includes(option.id);
                    return (
                      <label className={checked ? "drawer-theme-option is-selected" : "drawer-theme-option"} key={option.id}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => setThemeDraft((current) => current.includes(option.id)
                            ? current.filter((theme) => theme !== option.id)
                            : [...current, option.id])}
                        />
                        <span>{checked && <Check size={11} weight="bold" />}</span>
                        {option.label}
                      </label>
                    );
                  })}
                </div>
                <button type="button" className="drawer-theme-save" onClick={updateThemes} disabled={themesSaving}>
                  {themesSaving ? <SpinnerGap className="is-spinning" size={16} /> : <Tag size={16} weight="fill" />}
                  Save themes
                </button>
              </>
            ) : product.themes.length ? (
              <div className="drawer-theme-list">
                {product.themes.map((theme) => <span key={theme}>{theme}</span>)}
              </div>
            ) : (
              <span className="drawer-theme-empty">No themes assigned.</span>
            )}
          </section>
        )}

        {!catalogPreview && <section className="product-comments" aria-label="Comments and messages">
          <div className="product-comments-heading">
            <span><ChatCircleText size={18} weight="fill" /> Comments & messages</span>
            <small>Private to you and the admin team</small>
          </div>
          <form onSubmit={submitMessage}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value.slice(0, 1000))}
              placeholder="Leave feedback, ask a question, or request another asset..."
              aria-label="Message about this asset"
              rows={4}
            />
            <div>
              <small>{draft.length}/1000</small>
              <button type="submit" disabled={!draft.trim() || submitting}>
                {submitting ? <SpinnerGap className="is-spinning" size={15} weight="bold" /> : <PaperPlaneTilt size={15} weight="fill" />}
                Send message
              </button>
            </div>
          </form>
          <div className="my-message-list">
            {messagesLoading ? (
              <span className="message-empty"><SpinnerGap className="is-spinning" size={16} weight="bold" /> Loading your messages...</span>
            ) : messages.length ? messages.map((message) => (
              <article key={message.id}>
                <p>{message.body}</p>
                <time>{formatMessageTime(message.created_at)}</time>
              </article>
            )) : (
              <span className="message-empty">No messages yet.</span>
            )}
          </div>
        </section>}
        {catalogPreview && <p className="drawer-export-note"><Info size={15} weight="fill" /> {isAdmin ? "Choose an image above to update the product cover · Excel export is unchanged" : "Preview only · Excel export is unchanged"}</p>}
      </div>

      <div className="drawer-actions">
        <button className="button button-secondary" onClick={openOriginal}>
          <ArrowSquareOut size={18} weight="bold" /> Open original
        </button>
        <button className="button button-primary" onClick={onOpenDrive}>
          <FolderOpen size={18} weight="fill" /> Open in Drive
        </button>
      </div>
    </aside>
    {originalModal}
    </>
  );
}
