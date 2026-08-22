import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";

/** 学术 Markdown 渲染（D7）：GFM 表格 + KaTeX 公式 + 代码高亮。
 * memo 化：流式更新时仅文本变化的气泡重渲染。 */
export const Markdown = memo(function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-ra">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          rehypeKatex,
          [rehypeHighlight, { detect: true, ignoreMissing: true }],
        ]}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});
