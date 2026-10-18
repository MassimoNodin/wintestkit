import { describe, expect, it, vi } from "vitest";
import { disposeRunProfiles } from "../../src/testing/profiles";

describe("native Testing profiles", () => {
  it("disposes every registered run profile with its controller", () => {
    const profiles = [
      { dispose: vi.fn() },
      { dispose: vi.fn() },
      { dispose: vi.fn() },
    ];
    disposeRunProfiles(...(profiles as never[]));
    for (const profile of profiles) expect(profile.dispose).toHaveBeenCalledOnce();
  });
});
