import DOMPurify from "dompurify";
import { marked } from "marked";

marked.use({ breaks: true, gfm: true });

export function renderSafeMarkdown(value) {
  const source = String(value || "").slice(0, 12000);
  return DOMPurify.sanitize(marked.parse(source), {
    ALLOWED_TAGS: ["p", "br", "strong", "em", "code", "pre", "ul", "ol", "li", "h1", "h2", "h3", "blockquote", "a"],
    ALLOWED_ATTR: ["href", "title"],
    ALLOWED_URI_REGEXP: /^(?:(?:https?):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
  });
}
