import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getWiki, getPage } from "../lib/api";
import { useWikiStore } from "../stores/wiki";
import WikiSidebar from "../components/WikiSidebar";
import WikiContent from "../components/WikiContent";

export default function WikiView() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { wiki, setWiki, currentPageId, setCurrentPage } = useWikiStore();
  const [pageContent, setPageContent] = useState("");
  const [pageTitle, setPageTitle] = useState("");
  const [loading, setLoading] = useState(false);

  // load wiki structure if not already loaded
  useEffect(() => {
    if (!wiki && id) {
      getWiki(id).then((w) => {
        if ("error" in w) {
          navigate("/");
          return;
        }
        setWiki(w);
      });
    }
  }, [id, wiki]);

  // load page content when currentPageId changes
  useEffect(() => {
    if (!id || !currentPageId) return;
    setLoading(true);
    getPage(id, currentPageId).then((p) => {
      if ("error" in p) {
        setPageContent("页面不存在");
        setPageTitle("错误");
      } else {
        setPageContent(p.content);
        setPageTitle(p.title);
      }
      setLoading(false);
    });
  }, [id, currentPageId]);

  if (!wiki) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-500">
        正在加载 Wiki…
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-white">
      {/* sidebar */}
      <WikiSidebar
        sidebar={wiki.sidebar}
        currentPageId={currentPageId}
        projectName={wiki.project_name}
        onNavigate={(pageId) => setCurrentPage(pageId)}
        onChat={() => navigate(`/project/${id}/chat`)}
        onHome={() => navigate("/")}
        onMap={() => navigate(`/project/${id}/map`)}
        onDiff={() => navigate(`/project/${id}/diff`)}
        onCards={() => navigate(`/project/${id}/cards`)}
      />

      {/* main content */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-12 text-slate-400 animate-pulse">正在加载页面…</div>
        ) : (
          <WikiContent content={pageContent} title={pageTitle} />
        )}
      </div>
    </div>
  );
}
