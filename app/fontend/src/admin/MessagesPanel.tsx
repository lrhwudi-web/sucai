import { useEffect, useState } from "react";
import { ChatCenteredText, EnvelopeSimple, MagnifyingGlass, SpinnerGap, UserCircle } from "@phosphor-icons/react";
import { loadAdminMessages, markAdminMessageHandled } from "./adminService";
import type { AdminMessage } from "./types";

interface MessagesPanelProps {
  search: string;
  onNotify: (message: string) => void;
}

export function MessagesPanel({ search, onNotify }: MessagesPanelProps) {
  const [messages, setMessages] = useState<AdminMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const [markingId, setMarkingId] = useState<number | null>(null);

  useEffect(() => {
    let mounted = true;
    const timeout = window.setTimeout(() => {
      setLoading(true);
      setError("");
      loadAdminMessages(search, openOnly)
        .then((result) => {
          if (!mounted) return;
          setMessages(result.messages);
          setTotal(result.total);
        })
        .catch((caught) => {
          if (mounted) setError(caught instanceof Error ? caught.message : "客户留言加载失败");
        })
        .finally(() => {
          if (mounted) setLoading(false);
        });
    }, 220);
    return () => {
      mounted = false;
      window.clearTimeout(timeout);
    };
  }, [search, openOnly]);

  const markHandled = async (messageId: number) => {
    if (markingId !== null) return;
    setMarkingId(messageId);
    try {
      await markAdminMessageHandled(messageId);
      if (openOnly) {
        setMessages(current => current.filter(message => message.id !== messageId));
        setTotal(current => Math.max(0, current - 1));
      } else {
        setMessages(current => current.map(message => message.id === messageId ? { ...message, handledAt: new Date().toISOString() } : message));
      }
      window.dispatchEvent(new Event("kairay:pending-inquiries-changed"));
      onNotify("已标记为跟进，请确保已通过微信或邮件回复客户。");
    } catch (caught) {
      onNotify(caught instanceof Error ? caught.message : "客户询问更新失败");
    } finally {
      setMarkingId(null);
    }
  };

  return (
    <section className="admin-section messages-panel">
      <div className="admin-page-heading">
        <div>
          <span className="eyebrow">Customer feedback</span>
          <h1>客户留言</h1>
          <p>查看客户的产品询问，联系客户后标记已跟进。普通业务员只能看到自己客户的询问。</p>
        </div>
        <div className="message-total"><ChatCenteredText size={20} weight="fill" /><strong>{total}</strong><span>条留言</span></div>
      </div>

      <div className="message-filters" role="group" aria-label="筛选客户询问">
        <button type="button" className={openOnly ? "is-active" : ""} onClick={() => setOpenOnly(true)}>待跟进</button>
        <button type="button" className={!openOnly ? "is-active" : ""} onClick={() => setOpenOnly(false)}>全部</button>
      </div>

      {search && (
        <div className="message-search-state"><MagnifyingGlass size={15} weight="bold" />正在筛选“{search}”</div>
      )}

      {loading ? (
        <div className="messages-loading"><SpinnerGap className="is-spinning" size={22} weight="bold" />正在读取客户留言…</div>
      ) : error ? (
        <div className="messages-empty is-error"><strong>留言加载失败</strong><span>{error}</span></div>
      ) : messages.length ? (
        <div className="admin-message-list">
          {messages.map((message) => (
            <article key={message.id} className="admin-message-card">
              <header>
                <div>
                  <span className="message-sku">{message.sku}</span>
                  <strong>{message.productName || "未设置英文品名"}</strong>
                </div>
                <time>{message.createdAt}</time>
              </header>
              <p>{message.body}</p>
              <footer>
                <span><UserCircle size={16} weight="fill" />{message.userName || "Customer"}</span>
                <span><EnvelopeSimple size={16} weight="bold" />{message.userEmail}</span>
                {message.handledAt ? <span className="message-handled">已跟进</span> : <button type="button" disabled={markingId !== null} onClick={() => void markHandled(message.id)}>{markingId === message.id ? "处理中…" : "标记已跟进"}</button>}
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <div className="messages-empty">
          <ChatCenteredText size={34} weight="duotone" />
          <strong>{search ? "没有匹配的询问" : openOnly ? "没有待跟进的询问" : "还没有客户询问"}</strong>
          <span>{search ? "可以尝试搜索 SKU、客户邮箱或询问内容。" : "客户从商品目录或产品详情提交后，会显示在这里。"}</span>
        </div>
      )}
    </section>
  );
}
