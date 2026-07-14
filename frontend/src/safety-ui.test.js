// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { isDefaultCleanupSelection } from "./cleanup-module.js";
import { installCoverFallback } from "./collection-library.js";


describe("cleanup selection", () => {
  it("selects only pending confirmed-invalid items", () => {
    expect(isDefaultCleanupSelection({ verdict: "confirmed_invalid", execution_state: "pending" })).toBe(true);
    expect(isDefaultCleanupSelection({ verdict: "unknown", execution_state: "pending" })).toBe(false);
    expect(isDefaultCleanupSelection({ verdict: "review_required", execution_state: "pending" })).toBe(false);
    expect(isDefaultCleanupSelection({ verdict: "confirmed_invalid", execution_state: "removed" })).toBe(false);
  });
});

describe("cover fallback", () => {
  it("replaces a failed image with a fixed placeholder", () => {
    document.body.innerHTML = '<div id="root"><img id="cover"></div>';
    const image = document.getElementById("cover");
    installCoverFallback(image);
    image.dispatchEvent(new Event("error"));
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector(".video-cover-placeholder")).not.toBeNull();
  });
});
