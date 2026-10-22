import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Projects } from "../../src/projects";
import type { Project } from "../../src/server/serverManager";

const mocks = vi.hoisted(() => ({
  documents: [] as Array<{
    isDirty: boolean;
    languageId: string;
    uri: { scheme: string; fsPath: string };
    save: ReturnType<typeof vi.fn>;
  }>,
  prompt: vi.fn(),
}));
vi.mock("vscode", () => ({
  workspace: { get textDocuments() { return mocks.documents; } },
  window: { showWarningMessage: mocks.prompt },
}));
import { saveExecutionSources } from "../../src/testing/saveSources";

const project = { root: { toString: () => "project" } } as Project;
const projects = { projectFor: (uri: { fsPath: string }) =>
  uri.fsPath.startsWith("/project/") ? project : undefined } as unknown as Projects;
function document(file = "/project/test.py", languageId = "python", scheme = "file") {
  const source = {
    isDirty: true, languageId, uri: { scheme, fsPath: file },
    save: vi.fn(async () => { source.isDirty = false; return true; }),
  };
  mocks.documents.push(source);
  return source;
}
beforeEach(() => { mocks.documents = []; mocks.prompt.mockReset(); });

describe("execution source consent", () => {
  it("does not prompt for clean projects, unrelated projects or non-Python buffers", async () => {
    document("/other/test.py");
    document("/project/readme.md", "markdown");
    document("/project/new.py", "python", "untitled");
    expect(await saveExecutionSources(projects, project)).toBe(true);
    expect(mocks.prompt).not.toHaveBeenCalled();
  });
  it("blocks cancellation without saving anything", async () => {
    const source = document();
    expect(await saveExecutionSources(projects, project)).toBe(false);
    expect(source.save).not.toHaveBeenCalled();
    expect(mocks.prompt).toHaveBeenCalledWith(expect.stringContaining("from disk"), { modal: true }, "Save and Run");
  });
  it("saves all project Python dependencies only after explicit consent", async () => {
    const source = document();
    const page = document("/project/pages/main.py");
    const unrelated = document("/other/test.py");
    mocks.prompt.mockResolvedValue("Save and Run");
    expect(await saveExecutionSources(projects, project)).toBe(true);
    expect(source.save).toHaveBeenCalledOnce();
    expect(page.save).toHaveBeenCalledOnce();
    expect(unrelated.save).not.toHaveBeenCalled();
  });
  it.each(["failure", "exception", "still dirty", "new dirty source"])("blocks execution on %s", async (mode) => {
    const source = document();
    mocks.prompt.mockResolvedValue("Save and Run");
    source.save.mockImplementation(async () => {
      if (mode === "exception") throw new Error("write failed");
      if (mode === "failure") return false;
      if (mode === "new dirty source") { source.isDirty = false; document("/project/new.py"); }
      return true;
    });
    expect(await saveExecutionSources(projects, project)).toBe(false);
  });
});
