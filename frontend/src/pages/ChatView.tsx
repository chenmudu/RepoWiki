import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { streamChat } from "../lib/api";
import { useWikiStore } from "../stores/wiki";

export default function ChatView() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { chatMessages, addChatMessage, appendToLastChat, setLastChatReferences, settings } =
    useWikiStore();
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  function handleSend() {
    if (!input.trim() || !id || streaming) return;
    const question = input.trim();
    // the running conversation goes up with the question so follow-ups have
    // context; the store already holds every prior turn
    const history = chatMessages.map(({ role, content }) => ({ role, content }));
    setInput("");
    addChatMessage({ role: "user", content: question });
    addChatMessage({ role: "assistant", content: "" });
    setStreaming(true);

    streamChat(
      id,
      question,
      history,
      (data) => {
        if (data.references) setLastChatReferences(data.references);
        if (data.content) appendToLastChat(data.content);
      },
      () => setStreaming(false),
      settings.model || undefined,
    );
  }

  return (
    <div className="flex flex-col h-screen bg-slate-50">
      {/* header */}
      <header className="flex items-center gap-4 px-6 py-3 bg-white border-b border-slate-200">
        <button
          onClick={() => navigate(`/project/${id}`)}
          className="text-slate-500 hover:text-slate-700"
        >
          &larr; 返回 Wiki
        </button>
        <h1 className="text-lg font-semibold text-slate-800">关于这个代码库的问答</h1>
      </header>

      {/* messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {chatMessages.length === 0 && (
          <div className="text-center text-slate-400 mt-20">
            <p className="text-lg mb-2">可以问关于这个代码库的任何问题</p>
            <p className="text-sm">例如：“认证流程是怎么工作的？”</p>
          </div>
        )}
        {chatMessages.map((msg, i) => (
          <div
            key={i}
            className={`max-w-2xl ${msg.role === "user" ? "ml-auto" : "mr-auto"}`}
          >
            <div
              className={`rounded-lg px-4 py-3 ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-white border border-slate-200 text-slate-700"
              }`}
            >
              <pre className="whitespace-pre-wrap font-sans text-sm">{msg.content}</pre>
              {msg.references && msg.references.length > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
                  <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">来源</p>
                  {msg.references.map((ref, j) => (
                    <details key={j} className="group rounded border border-slate-200 bg-slate-50">
                      <summary className="cursor-pointer select-none px-3 py-1.5 text-xs font-mono text-blue-700 hover:bg-slate-100 rounded">
                        {ref.path}:{ref.line_start}-{ref.line_end}
                      </summary>
                      <pre className="px-3 py-2 text-xs font-mono text-slate-600 whitespace-pre-wrap border-t border-slate-200">{ref.snippet}</pre>
                      <div className="px-3 pb-2">
                        <Link
                          to={`/project/${id}/file/${ref.path}#L${ref.line_start}-L${ref.line_end}`}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          在文件视图中打开 →
                        </Link>
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* input */}
      <div className="px-6 py-4 bg-white border-t border-slate-200">
        <div className="max-w-2xl mx-auto flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="输入问题…"
            className="flex-1 px-4 py-2.5 rounded-lg border border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none text-sm"
            disabled={streaming}
          />
          <button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
