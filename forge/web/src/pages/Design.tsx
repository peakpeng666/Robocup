import { marked } from "marked";
import { useMemo } from "react";
import { Card, Empty, usePoll } from "../components/ui";

export function Design() {
  const doc = usePoll<{ markdown: string }>("/api/docs/design", 0);
  const html = useMemo(() => (doc.data ? (marked.parse(doc.data.markdown, { async: false }) as string) : ""), [doc.data]);
  if (!doc.data) return <Empty>加载中…</Empty>;
  return (
    <Card>
      {/* The document is a repository file served by the local server, not user-supplied content. */}
      <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
    </Card>
  );
}
