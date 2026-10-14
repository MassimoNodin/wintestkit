# 01 — Demo WPF App (T0.3) <a id="t03"></a>

The real app under test can't run on the development machine, so every engine, model, CLI and
extension test runs against this deliberately small WPF app. It imitates a **black-box** app:
almost nothing has an AutomationId, some names are duplicated, and it has a virtualized list, a
virtualized grid, async enabling, a modal WPF dialog, a Win32 MessageBox and a menu.

- **Depends on:** —
- **Size:** M
- **Files:** `demo/DemoApp/DemoApp.csproj`, `App.xaml`, `App.xaml.cs`, `MainWindow.xaml`,
  `MainWindow.xaml.cs`, `NoteDialog.xaml`, `NoteDialog.xaml.cs`, `Product.cs`, `demo/README.md`.

## Project

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net8.0-windows</TargetFramework>
    <UseWPF>true</UseWPF>
    <Nullable>enable</Nullable>
    <AssemblyName>DemoApp</AssemblyName>
    <RootNamespace>DemoApp</RootNamespace>
    <ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode>
  </PropertyGroup>
</Project>
```

Build: `dotnet build demo/DemoApp/DemoApp.csproj -c Release` →
`demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe`. No NuGet packages. Plain code-behind, no
MVVM framework.

## Command-line arguments (parsed in `App.OnStartup`)

| Arg | Effect |
|---|---|
| `--slow-start <ms>` | `Thread.Sleep(ms)` before the main window is created. Tests launch waiting. |
| `--title <text>` | Overrides the main window title (default `WTK Demo`). Lets tests run two instances / test regex titles. |
| `--load-delay <ms>` | Delay used by the Async "Load" button (default `2000`). |

Unknown args are ignored. Exit code 0 on normal close.

## Main window

- `Title = "WTK Demo"` (or `--title`), `Width=1000`, `Height=700`,
  `WindowStartupLocation=CenterScreen`.
- Root: `DockPanel`. Menu docked top. Status bar row docked bottom. Body: `Grid` with two equal
  columns, each a `StackPanel` with `Margin=8`.
- **No `x:Name`-derived AutomationIds leak in WPF** (WPF does not use `x:Name` as AutomationId),
  but to be safe do **not** set `AutomationProperties.AutomationId` anywhere except where this spec
  says so. Do **not** set `AutomationProperties.Name` or `LabeledBy` anywhere.

### Controls (left column, top to bottom)

| # | Control | Content / properties | AutomationId | Behaviour |
|---|---|---|---|---|
| L1 | `GroupBox` Header=`Credentials` | contains L2–L7 | — | — |
| L2 | `TextBlock` | `Username` | — | — |
| L3 | `TextBox` | Width 200 | — | — |
| L4 | `TextBlock` | `Password` | — | — |
| L5 | `PasswordBox` | Width 200 | — | — |
| L6 | `CheckBox` | `Remember me` | — | Toggling sets status `Remember: True` / `Remember: False` |
| L7 | `Button` | `Sign in` | — | If L3 == `admin` and L5 == `secret` → status `Welcome, admin`; else status `Invalid credentials` |
| L8 | `GroupBox` Header=`Panel A` | contains one `Button` `OK` | — | Click → status `A OK` |
| L9 | `GroupBox` Header=`Panel B` | contains one `Button` `OK` | — | Click → status `B OK` |
| L10 | `GroupBox` Header=`Async` | contains L11–L13 | — | — |
| L11 | `Button` | `Load` | — | Disables itself, sets status `Loading...`; after `--load-delay` ms (DispatcherTimer, not Thread.Sleep) makes L12 visible, enables L13, status `Loaded` |
| L12 | `TextBlock` | `Data loaded`, initially `Visibility=Collapsed` | — | (Collapsed elements are absent from the UIA tree — tests waiting for "attached") |
| L13 | `Button` | `Continue`, initially `IsEnabled=False` | — | Click → status `Continued` |
| L14 | `GroupBox` Header=`Choices` | contains L15 | — | — |
| L15 | `ComboBox` | items `Red`, `Green`, `Blue` (plain strings), no initial selection, Width 150 | `ColorCombo` | Selection change → status `Color: <item>` |
| L16 | `StackPanel` Orientation=Horizontal | contains L17, L18 | — | — |
| L17 | `Button` | `Open dialog` | — | Opens `NoteDialog` modally (`ShowDialog`, Owner = main window) |
| L18 | `Button` | `Show message` | — | `MessageBox.Show(this, "Hello from demo", "WTK Demo Message")`; after it closes → status `Message closed` |

### Controls (right column, top to bottom)

| # | Control | Content / properties | AutomationId | Behaviour |
|---|---|---|---|---|
| R1 | `TextBlock` | `Items` | — | — |
| R2 | `ListBox` | 500 string items `Item 1` … `Item 500`, `Height=180`, default virtualization (`VirtualizingStackPanel`, do not disable) | — | Selection change → status `Selected: Item N` |
| R3 | `TextBlock` | `Products` | — | — |
| R4 | `DataGrid` | `ItemsSource` = 200 `Product` objects, `AutoGenerateColumns=False`, `IsReadOnly=True`, `Height=260`, `SelectionMode=Single`, columns `Id` (int), `Name` (string), `Qty` (int) | — | Selection change → status `Row: <Name>` |

`Product` is a plain class `{ int Id; string Name; int Qty; }` with properties; **do not override
`ToString()`** (black-box realism: row names will be `DemoApp.Product`). Data: `Id = i`,
`Name = $"Product {i}"`, `Qty = (i * 7) % 23` for `i = 1..200`.

### Status bar (docked bottom)

| # | Control | Content | AutomationId |
|---|---|---|---|
| S1 | `TextBlock` | initial `Ready` | `StatusText` |

`StatusText` is the **only** element in the main window with an AutomationId besides `ColorCombo`.

### Menu (docked top)

| Menu | Item | Behaviour |
|---|---|---|
| `File` | `Reset` | Clears L3, L5, unchecks L6, resets L11–L13 to initial state, clears L15/R2/R4 selections, status `Ready` |
| `File` | `Exit` | `Close()` |
| `Help` | `About` | `MessageBox.Show(this, "WTK Demo 1.0", "About")` |

Menu item headers are plain text (no access-key underscores, so names are exactly `File`, `Reset`,
etc.).

## NoteDialog (modal WPF window)

- `Title = "WTK Demo - Dialog"`, `Width=360`, `Height=180`, `WindowStartupLocation=CenterOwner`,
  `ResizeMode=NoResize`, `ShowInTaskbar=False`.
- Contents: `TextBlock` `Enter a note:`; `TextBox` (no AutomationId); buttons `Save` and `Cancel`
  (`IsCancel=True`).
- `Save` → main status `Note: <text>` and closes. `Cancel` → status `Note cancelled` and closes.

## Expected UI Automation view (for reference — T1.x tasks verify)

Implementers of T0.3 should open the app in **Accessibility Insights for Windows** (or `inspect.exe`)
and fill in/correct this table in `demo/README.md`. Expected values:

| Element | ControlType | ClassName | Name | AutomationId | FrameworkId |
|---|---|---|---|---|---|
| Main window | Window | `Window` | `WTK Demo` | `""` | WPF |
| Menu bar | Menu | `Menu` | `""` | `""` | WPF |
| `File` | MenuItem | `MenuItem` | `File` | `""` | WPF |
| Credentials | Group | `GroupBox` | `Credentials` | `""` | WPF |
| Username box | Edit | `TextBox` | `""` | `""` | WPF |
| Password box | Edit | `PasswordBox` | `""` | `""` | WPF |
| Remember me | CheckBox | `CheckBox` | `Remember me` | `""` | WPF |
| Sign in | Button | `Button` | `Sign in` | `""` | WPF |
| Panel A OK / Panel B OK | Button | `Button` | `OK` | `""` | WPF |
| Data loaded (after load) | Text | `TextBlock` | `Data loaded` | `""` | WPF |
| Color combo | ComboBox | `ComboBox` | `""` | `ColorCombo` | WPF |
| Items list | List | `ListBox` | `""` | `""` | WPF |
| List item | ListItem | `ListBoxItem` | `Item 1` | `""` | WPF |
| Products grid | DataGrid | `DataGrid` | `""` | `""` | WPF |
| Grid row | DataItem | `DataGridRow` | `DemoApp.Product` | `""` | WPF |
| Grid cell | (verify: Custom/DataItem/Text) | `DataGridCell` | cell text | `""` | WPF |
| Status | Text | `TextBlock` | `Ready` | `StatusText` | WPF |
| Note dialog | Window | `Window` | `WTK Demo - Dialog` | `""` | WPF |
| MessageBox | Window | `#32770` | `WTK Demo Message` | `""` | Win32 |
| MessageBox OK | Button | `Button` | `OK` | `2` (verify) | Win32 |

## Done when

- `dotnet build demo/DemoApp/DemoApp.csproj -c Release` succeeds with zero warnings.
- Every behaviour in the tables works when done by hand.
- `demo/README.md` contains build/run instructions, the argument table, and the verified UIA table
  (corrected from what the inspector actually shows).
