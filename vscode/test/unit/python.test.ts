import { expect, it, vi } from "vitest";

vi.mock("vscode", () => ({}));
vi.mock("@vscode/python-extension", () => ({ PythonExtension: {} }));

import { installArguments } from "../../src/python";
import { PYTHON_REQUIREMENT } from "../../src/compatibility";

it("constrains production package installation to the supported range", async () => {
  expect(await installArguments()).toEqual([
    "-m", "pip", "install", "--upgrade", "--force-reinstall", PYTHON_REQUIREMENT,
  ]);
});
