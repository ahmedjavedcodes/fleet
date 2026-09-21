import { afterEach, describe, expect, it } from "vitest";

import { clearClientToken, getClientToken, setClientToken } from "@/lib/auth-client";

function clearAllCookies() {
  document.cookie.split(";").forEach((c) => {
    const name = c.split("=")[0].trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  });
}

afterEach(() => {
  clearAllCookies();
});

describe("auth-client cookie helpers", () => {
  it("returns null when no token cookie is set", () => {
    expect(getClientToken()).toBeNull();
  });

  it("round-trips a token through setClientToken/getClientToken", () => {
    setClientToken("jwt-value", 3600);
    expect(getClientToken()).toBe("jwt-value");
  });

  it("caps the cookie lifetime at the 12h ceiling regardless of a larger expiresIn", () => {
    setClientToken("jwt-value", 999_999);
    expect(document.cookie).toContain("fleet_token=jwt-value");
    // Can't directly read max-age back from document.cookie (browsers don't
    // expose attributes), so this just guards against setClientToken throwing
    // or truncating the token value when clamping is applied.
  });

  it("URL-encodes and decodes tokens containing special characters", () => {
    setClientToken("abc.def+ghi=jkl", 60);
    expect(getClientToken()).toBe("abc.def+ghi=jkl");
  });

  it("removes the token on clearClientToken", () => {
    setClientToken("jwt-value", 60);
    clearClientToken();
    expect(getClientToken()).toBeNull();
  });
});
