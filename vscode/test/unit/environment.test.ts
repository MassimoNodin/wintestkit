import { describe, expect, it, vi } from "vitest";
import type { Project } from "../../src/server/serverManager";
import { offerDoctorForRun } from "../../src/testing/environment";

const project = { root: { fsPath: "C:/specific-project" } } as Project;

describe("environment-block doctor action", () => {
  it("offers the doctor only for the backend's verified environment exit code", async () => {
    const show = vi.fn(async () => "Check Environment");
    const execute = vi.fn(async () => undefined);
    await offerDoctorForRun(1, project, show, execute);
    await offerDoctorForRun(2, project, show, execute);
    await offerDoctorForRun(4, project, show, execute);
    expect(show).not.toHaveBeenCalled();
    expect(execute).not.toHaveBeenCalled();
    await offerDoctorForRun(3, project, show, execute);
    expect(show).toHaveBeenCalledOnce();
    expect(execute).toHaveBeenCalledWith("wintestkit.runDoctor", {
      resourceUri: project.root,
    });
  });
  it("does nothing when the doctor action is dismissed", async () => {
    const show = vi.fn(async () => undefined);
    const execute = vi.fn(async () => undefined);
    await offerDoctorForRun(3, project, show, execute);
    expect(execute).not.toHaveBeenCalled();
  });
});
