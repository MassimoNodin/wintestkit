import { readFileSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type {
  ElementInfo,
  Diagnostic,
  DiscoveryResult,
  StepEvent,
  Results,
  Suggestion,
  RunEvent,
} from "../../src/protocol/generated";

const elementInfo = {
  automationId: "",
  name: "Sign in",
  controlType: "Button",
  className: "Button",
  frameworkId: "WPF",
  processId: 1234,
  rect: {
    left: 10,
    top: 20,
    width: 80,
    height: 30,
  },
  isEnabled: true,
  isOffscreen: false,
  hasKeyboardFocus: false,
  runtimeId: "42.1234.4.17",
  patterns: ["Invoke"],
} satisfies ElementInfo;

const diagnostic = {
  kind: "ambiguous",
  message: "Two matching OK buttons",
  locator: 'Button "OK"',
  searchedIn: 'Window "WTK Demo"',
  matchCount: 2,
  candidates: [
    {
      info: {
        automationId: "",
        name: "OK",
        controlType: "Button",
        className: "Button",
        frameworkId: "WPF",
        processId: 1234,
        rect: {
          left: 10,
          top: 20,
          width: 80,
          height: 30,
        },
        isEnabled: true,
        isOffscreen: false,
        hasKeyboardFocus: false,
        runtimeId: "42.1234.4.17",
        patterns: ["Invoke"],
      },
      score: 2,
      mismatches: [],
    },
    {
      info: {
        automationId: "",
        name: "OK",
        controlType: "Button",
        className: "Button",
        frameworkId: "WPF",
        processId: 1234,
        rect: {
          left: 10,
          top: 20,
          width: 80,
          height: 30,
        },
        isEnabled: true,
        isOffscreen: false,
        hasKeyboardFocus: false,
        runtimeId: "42.1234.4.18",
        patterns: ["Invoke"],
      },
      score: 2,
      mismatches: [],
    },
  ],
} satisfies Diagnostic;

const discovery = {
  version: 1,
  root: "C:/wtk/examples/demo-tests",
  tests: [
    {
      id: "tests/test_login.py::test_sign_in",
      file: "C:/wtk/examples/demo-tests/tests/test_login.py",
      name: "test_sign_in",
      kind: "function",
      parent: null,
      range: {
        start: {
          line: 0,
          character: 0,
        },
        end: {
          line: 4,
          character: 0,
        },
      },
      nameRange: {
        start: {
          line: 1,
          character: 4,
        },
        end: {
          line: 1,
          character: 16,
        },
      },
    },
  ],
  screens: [
    {
      id: "screens/main.py::MainScreen",
      file: "C:/wtk/examples/demo-tests/screens/main.py",
      name: "MainScreen",
      qualname: "MainScreen",
      bases: ["Screen"],
      range: {
        start: {
          line: 0,
          character: 0,
        },
        end: {
          line: 4,
          character: 0,
        },
      },
      nameRange: {
        start: {
          line: 0,
          character: 6,
        },
        end: {
          line: 0,
          character: 16,
        },
      },
      elements: [
        {
          id: "screens/main.py::MainScreen.sign_in",
          name: "sign_in",
          qualname: "MainScreen.sign_in",
          kind: "element",
          range: {
            start: {
              line: 0,
              character: 0,
            },
            end: {
              line: 4,
              character: 0,
            },
          },
          nameRange: {
            start: {
              line: 2,
              character: 4,
            },
            end: {
              line: 2,
              character: 11,
            },
          },
          locator: {
            name: "Sign in",
            controlType: "Button",
            within: {
              name: "Credentials",
              controlType: "Group",
            },
            window: {
              title: {
                regex: "^WTK Demo",
                flags: "i",
              },
              process: "DemoApp.exe",
            },
          },
          withinName: "credentials",
          windowName: "window",
          dynamic: false,
        },
      ],
    },
  ],
  errors: [
    {
      file: "C:/wtk/examples/demo-tests/tests/test_broken.py",
      message: "invalid syntax",
      line: 2,
    },
  ],
} satisfies DiscoveryResult;

const step = {
  seq: 1,
  action: "type",
  target: "MainScreen.password",
  locator: "Edit class=PasswordBox",
  args: {
    text: "***",
    clear: true,
  },
  start: 1791936000,
  duration: 0.05,
  status: "passed",
  screenshot: "artifacts/sign-in/step-1.png",
} satisfies StepEvent;

const results = {
  version: 1,
  startedAt: 1791936000,
  finishedAt: 1791936000.5,
  duration: 0.5,
  environment: {
    python: "3.12.0",
    wintestkit: "0.1.0",
    windows: "Windows 11",
    machine: "DEMO",
    screen: {
      width: 1920,
      height: 1080,
      scale: 1.25,
    },
  },
  summary: {
    total: 1,
    passed: 1,
    failed: 0,
    skipped: 0,
    errors: 0,
    duration: 0.5,
  },
  tests: [
    {
      id: "tests/test_login.py::test_sign_in[admin-secret]",
      file: "C:/wtk/examples/demo-tests/tests/test_login.py",
      line: 1,
      name: "test_sign_in[admin-secret]",
      outcome: "passed",
      duration: 0.2,
      steps: [
        {
          seq: 1,
          action: "type",
          target: "MainScreen.password",
          locator: "Edit class=PasswordBox",
          args: {
            text: "***",
            clear: true,
          },
          start: 1791936000,
          duration: 0.05,
          status: "passed",
          screenshot: "artifacts/sign-in/step-1.png",
        },
      ],
      screenshots: ["artifacts/sign-in/step-1.png"],
      treeDump: "artifacts/sign-in/tree.txt",
      stdout: "Signed in\n",
      stderr: "",
      log: "",
    },
  ],
} satisfies Results;

const suggestion = {
  locator: {
    name: "Sign in",
    controlType: "Button",
    within: {
      name: "Credentials",
      controlType: "Group",
    },
  },
  code: 'Element(control_type="Button", name="Sign in", within=credentials)',
  attributeName: "sign_in",
  helpers: [
    {
      attributeName: "credentials",
      code: 'Element(control_type="Group", name="Credentials")',
      locator: {
        controlType: "Group",
        name: "Credentials",
      },
    },
  ],
  unique: true,
  matchCount: 1,
  strategy: "within",
  window: {
    code: 'Window(title="WTK Demo")',
    locator: {
      title: "WTK Demo",
      process: "DemoApp.exe",
    },
  },
} satisfies Suggestion;

const events = [
  {
    event: "session_start",
    time: 1791936000,
    root: "C:/wtk/examples/demo-tests",
    pid: 1234,
    wintestkitVersion: "0.1.0",
  },
  {
    event: "collected",
    time: 1791936000.1,
    tests: [
      {
        id: "tests/test_login.py::test_sign_in[admin-secret]",
        file: "C:/wtk/examples/demo-tests/tests/test_login.py",
        line: 1,
        name: "test_sign_in[admin-secret]",
        parent: "tests/test_login.py::test_sign_in",
      },
    ],
    errors: [],
  },
  {
    event: "test_start",
    time: 1791936000.2,
    id: "tests/test_login.py::test_sign_in[admin-secret]",
  },
  {
    event: "step",
    time: 1791936000.25,
    id: "tests/test_login.py::test_sign_in[admin-secret]",
    step: {
      seq: 1,
      action: "type",
      target: "MainScreen.password",
      locator: "Edit class=PasswordBox",
      args: {
        text: "***",
        clear: true,
      },
      start: 1791936000,
      duration: 0.05,
      status: "passed",
      screenshot: "artifacts/sign-in/step-1.png",
    },
  },
  {
    event: "test_output",
    time: 1791936000.3,
    id: "tests/test_login.py::test_sign_in[admin-secret]",
    stream: "stdout",
    text: "Signed in\n",
  },
  {
    event: "test_end",
    time: 1791936000.4,
    id: "tests/test_login.py::test_sign_in[admin-secret]",
    outcome: "passed",
    duration: 0.2,
    location: {
      file: "C:/wtk/examples/demo-tests/tests/test_login.py",
      line: 1,
    },
    screenshots: [
      "C:/wtk/examples/demo-tests/wtk-report/artifacts/sign-in/step-1.png",
    ],
    artifactsDir: "C:/wtk/examples/demo-tests/wtk-report/artifacts/sign-in",
  },
  {
    event: "session_end",
    time: 1791936000.5,
    exitCode: 0,
    summary: {
      total: 1,
      passed: 1,
      failed: 0,
      skipped: 0,
      errors: 0,
      duration: 0.5,
    },
    reportPath: "C:/wtk/examples/demo-tests/wtk-report/index.html",
    junitPath: "C:/wtk/examples/demo-tests/junit.xml",
  },
] satisfies RunEvent[];

const fixturesDirectory = resolve("../python/tests/contract/fixtures");
const fixtureExamples = {
  "element-info.json": elementInfo,
  "diagnostic.json": diagnostic,
  "discovery.json": discovery,
  "step.json": step,
  "results.json": results,
  "suggestion.json": suggestion,
};

describe("protocol contracts", () => {
  it.each(Object.entries(fixtureExamples))(
    "%s matches its statically type-checked example",
    (filename, example) => {
      const fixture: unknown = JSON.parse(
        readFileSync(resolve(fixturesDirectory, filename), "utf8"),
      );
      expect(fixture).toEqual(example);
    },
  );

  it("loads every NDJSON event variant against the typed examples", () => {
    const fixture: unknown[] = readFileSync(
      resolve(fixturesDirectory, "events.ndjson"),
      "utf8",
    )
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line) as unknown);
    expect(fixture).toEqual(events);
  });

  it("commits exactly the reproducible output for every schema definition", () => {
    const generatedPath = resolve("src/protocol/generated.ts");
    const committed = readFileSync(generatedPath, "utf8");
    for (let run = 0; run < 2; run++) {
      const result = spawnSync(process.execPath, ["scripts/gen-types.mjs"], {
        encoding: "utf8",
      });
      if (result.error) throw result.error;
      expect(result.status, result.stderr).toBe(0);
      expect(readFileSync(generatedPath, "utf8")).toBe(committed);
    }
    for (const filename of readdirSync("../schemas").filter((file) =>
      file.endsWith(".schema.json"),
    )) {
      const schema: { $defs: Record<string, unknown> } = JSON.parse(
        readFileSync(resolve("../schemas", filename), "utf8"),
      );
      for (const name of Object.keys(schema.$defs)) {
        expect(committed).toMatch(
          new RegExp(`export (?:interface|type) ${name}\\b`),
        );
      }
    }
  }, 30000);
});
