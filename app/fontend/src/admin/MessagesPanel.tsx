import { useEffect, useState } from "react";
import { ChatCenteredText, EnvelopeSimple, MagnifyingGlass, SpinnerGap, UserCircle } from "@phosphor-icons/react";
import { loadAdminMessages } from "./adminService";
import type { AdminMessage } from "./types";

interface MessagesPanelProps {
  search: string;
}

export function MessagesPanel({ search }: MessagesPanelProps) {
  const [messages, setMessages] = useState<AdminMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    const timeout = window.setTimeout(() => {
      setLoading(true);
      setError("");
      loadAdminMessages(search)
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
  }, [search]);

  return (
    <section className="admin-section messages-panel">
      <div className="admin-page-heading">
        <div>
          <span className="eyebrow">Customer feedback</span>
          <h1>客户留言</h1>
          <p>查看客户针对具体 SKU 提交的问题、需求与素材反馈。客户之间无法互相看到留言。</p>
        </div>
        <div className="message-total"><ChatCenteredText size={20} weight="fill" /><strong>{total}</strong><span>条留言</span></div>
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
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <div className="messages-empty">
          <ChatCenteredText size={34} weight="duotone" />
          <strong>{search ? "没有匹配的留言" : "还没有客户留言"}</strong>
          <span>{search ? "可以尝试搜索 SKU、客户邮箱或留言内容。" : "客户从产品详情提交后，留言会显示在这里。"}</span>
        </div>
      )}
    </section>
  );
}
