/**
 * The rows of the Properties sidebar's Basic view. One user setting holds them as group-qualified keys,
 * "<group>/<row name>", for example "Standard/Enabled" or "Win32 Window/Window Class".
 */
export const BASIC_SETTING = "basicProperties";
export const MAX_BASIC_PROPERTIES = 256;
/** A UI Automation property name, as the server reads it with `include`. */
export const PROPERTY_NAME = /^[A-Za-z][A-Za-z0-9]{0,63}$/;
export const BASIC_GROUPS = ["Standard", "Extended", ".NET", "Win32 Window", "UI Automation"] as const;
const BASIC_KEY = new RegExp(
  "^(" + BASIC_GROUPS.map((group) => group.replace(".", "\\.")).join("|") + ")/([^\\u0000-\\u001f]{1,200})$",
);

/** What the Basic view shows until the user changes it. package.json carries the same list as the setting's default. */
export const DEFAULT_BASIC_PROPERTIES: readonly string[] = [
  "Standard/Enabled",
  "Standard/Height",
  "Standard/Name",
  "Standard/Parent",
  "Standard/Visible",
  "Standard/Width",
  ".NET/ClrClassName",
  ".NET/ClrFullClassName",
  ".NET/WPFControlName",
  ".NET/WinFormsControlName",
  ".NET/WPFControlOrdinalNo",
  ".NET/WPFControlText",
  ".NET/WinFormsControlText",
  "Win32 Window/Window Class",
  "Win32 Window/Control ID",
  "Win32 Window/Text",
  "Win32 Window/Handle",
  "Win32 Window/Styles",
];

export function isBasicKey(value: unknown): value is string {
  return typeof value === "string" && BASIC_KEY.test(value);
}

/** A stored list without the entries that are not keys and without repeats; anything but a list is empty. */
export function normalizeBasicProperties(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter(isBasicKey))].slice(0, MAX_BASIC_PROPERTIES);
}

/** The UI Automation properties the server must read with every selection for the Basic view to show them. */
export function basicUiaNames(keys: readonly string[]): string[] {
  const prefix = "UI Automation/";
  return keys
    .filter((key) => key.startsWith(prefix))
    .map((key) => key.slice(prefix.length))
    .filter((name) => PROPERTY_NAME.test(name));
}
