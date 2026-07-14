// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { renderSafeMarkdown } from "./markdown.js";


describe("renderSafeMarkdown", () => {
  it("renders markdown and strips scripts and event handlers", () => {
    const html = renderSafeMarkdown("## 结论\n\n**安全**<img src=x onerror=alert(1)><script>alert(1)</script>");
    expect(html).toContain("<h2>结论</h2>");
    expect(html).toContain("<strong>安全</strong>");
    expect(html).not.toContain("script");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("<img");
  });

  it("rejects javascript links", () => {
    const html = renderSafeMarkdown("[bad](javascript:alert(1)) [good](https://example.com)");
    expect(html).not.toContain("javascript:");
    expect(html).toContain("https://example.com");
  });
});
