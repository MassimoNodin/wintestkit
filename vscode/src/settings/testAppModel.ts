import * as path from "node:path";
import type { ApplicationState } from "../statusBar";

export type Tone = "ok" | "busy" | "warn" | "error" | "idle";

/** What a tile does: pick tiles open a quick pick, action tiles run an application command. */
export type TileId =
  | "app"
  | "mode"
  | "project"
  | "launch"
  | "restart"
  | "close"
  | "refresh"
  | "init"
  | "doctor"
  | "dismiss"
  | "output";

export interface Tile {
  id: TileId;
  title: string;
  subtitle?: string;
  /** The application's own icon (a PNG data URI), shown instead of the codicon when known. */
  icon?: string;
  codicon: string;
  /** Colours the codicon: launch green, stop red, attach/project orange, and so on. */
  tone?: "launch" | "stop" | "link" | "project" | "busy" | "warn";
  chevron?: boolean;
  /** Draws attention: something about this tile explains a failure. */
  alert?: boolean;
  /** Shown but not pressable (it keeps its tooltip, which says why). */
  locked?: boolean;
  /** The codicon shown at the tile's trailing edge (default chevron-down): what pressing it opens. */
  trailing?: string;
  disabled?: boolean;
  /** The action this tile started is running: it shows a spinner and a short status. */
  busy?: boolean;
  tooltip?: string;
}

export interface TestAppModel {
  kind: "empty" | "untrusted" | "app";
  status: { label: string; tone: Tone };
  tiles: Tile[];
  message?: {
    tone: Tone;
    text: string;
    action?: { id: TileId; label: string };
    /** A codicon shown before the text, in the tone's colour. */
    icon?: string;
    /** The tile id the message's dismiss button sends. */
    dismiss?: TileId;
  };
  /** Shown as a badge on the WinTestKit icon in the activity bar, with this tooltip. */
  badge?: string;
}

export interface TestAppInput {
  project?: { name: string };
  trusted: boolean;
  /** Projects in the workspace; the project tile only offers a switch when there are several. */
  projectCount?: number;
  /** Name of the workspace folder holding the project, shown above the project name. */
  workspaceName?: string;
  /** Flat settings as read from the project's configuration files. */
  config?: Record<string, unknown>;
  configError?: string;
  state?: ApplicationState;
  icon?: string;
}

const MODES: Record<
  string,
  { title: string; codicon: string; description: string }
> = {
  attach: {
    title: "Attach",
    codicon: "link",
    description:
      "Use the app that is already running. WinTestKit never starts or closes it.",
  },
  "per-session": {
    title: "Launch for tests",
    codicon: "rocket",
    description:
      "Start the app for the tests and close it when they finish. A copy that is already running is closed first.",
  },
  // Still honoured when set in the settings file, but not offered in the picker.
  "per-test": {
    title: "Launch per test",
    codicon: "rocket",
    description:
      "Start a fresh app for every test and close it afterwards. Set in the settings file.",
  },
};

/** The two ways to get the app, in the order the picker shows them. */
export const modeChoices = ["per-session", "attach"].map((id) => ({
  id,
  ...MODES[id],
}));

/** One short phrase for where a launch is, shown under the clicked button's title. */
function startingStatus(stage?: "process" | "window"): string {
  if (stage === "window") return "Waiting for window";
  if (stage === "process") return "Waiting for app";
  return "Starting process";
}

export function buildTestAppModel(input: TestAppInput): TestAppModel {
  const bare = (
    kind: TestAppModel["kind"],
    status: TestAppModel["status"],
    text: string,
    tiles: Tile[],
    tone: Tone = "idle",
  ): TestAppModel => ({
    kind,
    status,
    tiles,
    message: { tone, text },
  });
  if (!input.project)
    return bare(
      "empty",
      { label: "Not set up", tone: "idle" },
      "No WinTestKit project found in this workspace.",
      [
        {
          id: "init",
          title: "Initialize Project",
          codicon: "add",
          tone: "launch",
        },
      ],
    );
  if (!input.trusted)
    return bare(
      "untrusted",
      { label: "Workspace not trusted", tone: "warn" },
      "Trust this workspace to read its configuration and talk to the application.",
      [],
      "warn",
    );
  if (input.configError)
    return bare(
      "empty",
      { label: "Configuration error", tone: "error" },
      input.configError,
      [],
      "error",
    );

  const config = input.config ?? {};
  const file =
    typeof config["app.path"] === "string" && config["app.path"].trim()
      ? config["app.path"]
      : undefined;
  const processName =
    typeof config["app.process"] === "string" && config["app.process"].trim()
      ? config["app.process"]
      : undefined;
  const target = file || processName;
  const launchable = !!file;
  const modeId = String(config.launch ?? "per-session");
  const mode = MODES[modeId] ?? {
    title: modeId,
    codicon: "history",
    description: modeId,
  };
  const state = input.state;
  const pids = state?.running ? state.pids : undefined;

  const appTile: Tile = target
    ? {
        id: "app",
        title: (path.win32.basename(target) || "Test Target").replace(
          /\.exe$/i,
          "",
        ),
        subtitle: pids?.length
          ? (pids.length > 1 ? "PIDs " : "PID ") + pids.join(", ")
          : undefined,
        icon: input.icon,
        codicon: "window",
        // The running app is the target, so it cannot be swapped out from under the tests.
        ...(pids
          ? {
              locked: true,
              tooltip:
                target +
                "\nThe application is running. Close it to choose a different one.",
            }
          : {
              chevron: true,
              trailing: "list-selection",
              tooltip: target + "\nChoose a different application",
            }),
      }
    : {
        id: "app",
        title: "Choose app",
        codicon: "window",
        tone: "warn",
        chevron: true,
        trailing: "list-selection",
        tooltip: "Pick the application to test",
      };
  const modeTile: Tile = {
    id: "mode",
    title: mode.title,
    codicon: mode.codicon,
    tone: "link",
    chevron: true,
    trailing: "list-selection",
    tooltip: mode.description + "\nChoose how the app is started",
  };
  const projectTile: Tile = {
    id: "project",
    title: input.workspaceName || input.project.name,
    subtitle:
      input.workspaceName && input.workspaceName !== input.project.name
        ? input.project.name
        : undefined,
    codicon: "folder-opened",
    tone: "project",
    chevron: true,
    trailing: "go-to-file",
    tooltip: "Show the project folder in the Explorer",
  };
  const tiles: Tile[] = [projectTile, appTile, modeTile];
  const model: TestAppModel = {
    kind: "app",
    status: { label: "Checking…", tone: "idle" },
    tiles,
  };

  const transition = state?.transition;
  if (transition) {
    const action = transition.action;
    const detail =
      transition.kind === "stopping"
        ? "Closing windows"
        : startingStatus(transition.stage);
    const labels = {
      launch: "Starting…",
      restart: "Restarting…",
      close: "Closing…",
    };
    model.status = { label: labels[action], tone: "busy" };
    const busy = (id: "launch" | "restart" | "close"): Tile => ({
      id,
      title: labels[id],
      subtitle: detail,
      codicon: "loading",
      tone: "busy",
      disabled: true,
      busy: true,
    });
    const idle = (
      id: "restart" | "close",
      title: string,
      codicon: string,
      tone: "launch" | "stop",
    ): Tile => ({ id, title, codicon, tone, disabled: true });
    if (action === "launch") tiles.push(busy("launch"));
    else if (action === "restart")
      tiles.push(busy("restart"), idle("close", "Close", "debug-stop", "stop"));
    else {
      if (launchable)
        tiles.push(idle("restart", "Restart", "debug-restart", "launch"));
      tiles.push(busy("close"));
    }
    return model;
  }

  if (!state) {
    tiles.push({
      id: "launch",
      title: "Launch",
      codicon: "debug-start",
      tone: "launch",
      disabled: true,
    });
    return model;
  }

  if (state.error) {
    model.status = { label: "Status unavailable", tone: "error" };
    model.message = {
      tone: "error",
      text: state.error,
      action: { id: "output", label: "Show output" },
    };
    tiles.push({
      id: "refresh",
      title: "Retry",
      codicon: "refresh",
      tone: "launch",
    });
    return model;
  }

  if (state.running) {
    model.status = { label: "Running", tone: "ok" };
    if (launchable)
      tiles.push({
        id: "restart",
        title: "Restart",
        codicon: "debug-restart",
        tone: "launch",
      });
    tiles.push({
      id: "close",
      title: "Close",
      codicon: "debug-stop",
      tone: "stop",
    });
    return model;
  }

  if (state.failure) {
    model.status = { label: "Failed", tone: "error" };
    const verb =
      state.failure.action === "close"
        ? "Closing the app failed"
        : "The app did not start";
    model.message = {
      tone: "error",
      text: verb + ": " + state.failure.message,
      action: state.failure.environment
        ? { id: "doctor", label: "Check Environment" }
        : { id: "output", label: "Show output" },
    };
    tiles.push(
      launchable
        ? {
            id: "launch",
            title: "Try again",
            codicon: "debug-start",
            tone: "launch",
          }
        : {
            id: "refresh",
            title: "Check again",
            codicon: "refresh",
            tone: "launch",
          },
    );
    return model;
  }

  if (launchable) {
    model.status = { label: "Stopped", tone: "idle" };
    tiles.push({
      id: "launch",
      title: "Launch",
      codicon: "debug-start",
      tone: "launch",
      disabled: !target,
    });
  } else {
    const spawning = modeId !== "attach";
    model.status = {
      label: spawning ? "Needs an executable" : "Waiting for the app",
      tone: "warn",
    };
    if (target)
      model.message = {
        tone: "warn",
        text: spawning
          ? "Launch for tests starts the app, so it needs an executable. Choose one with the application tile, or switch the mode to Attach."
          : "WinTestKit attaches to " +
            (processName ?? "the app") +
            " but never starts it. Start the app yourself, or choose an executable to launch.",
      };
    tiles.push({
      id: "refresh",
      title: "Check again",
      codicon: "refresh",
      tone: "launch",
      disabled: !target,
    });
  }
  if (state.attachFailure && modeId === "attach") {
    const name = processName ?? "the app";
    model.status = { label: "Tests need the app running", tone: "error" };
    Object.assign(modeTile, {
      title: "Attach",
      subtitle: "App wasn't running",
      codicon: "warning",
      tone: "stop",
      alert: true,
      tooltip:
        "The last test run failed: the launch mode is Attach, so WinTestKit did not start " +
        name +
        " and it wasn't running.\nClick to change the launch mode.",
    });
    model.message = {
      tone: "error",
      text:
        "The last test run failed because " +
        name +
        " wasn't running. Attach mode never starts the app: start it yourself, or change the launch mode to Launch for tests.",
      action: { id: "mode", label: "Change launch mode" },
      icon: "warning",
      dismiss: "dismiss",
    };
    model.badge =
      "The last test run failed: " + name + " wasn't running in Attach mode.";
  }
  return model;
}
