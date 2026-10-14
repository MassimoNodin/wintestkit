# WPF demo app

The T0.3 black-box test target runs on Windows with .NET 8. It has no NuGet dependencies.
Build with the .NET 8 SDK; running the executable requires the .NET 8 Windows Desktop runtime.

From the repository root:

```powershell
dotnet build demo/DemoApp/DemoApp.csproj -c Release
& ./demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe
& ./demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe --slow-start 1500 --title "WTK Demo - Slow" --load-delay 3000
```

`app.manifest` declares PerMonitorV2 DPI awareness. Normal close and File > Exit return exit code 0.

## Startup arguments

| Argument | Default | Effect |
|---|---|---|
| `--slow-start <ms>` | `0` | Blocks startup before creating the main window. |
| `--title <text>` | `WTK Demo` | Changes the main-window title. Quote titles containing spaces. |
| `--load-delay <ms>` | `2000` | Sets the asynchronous Load delay, using a DispatcherTimer. |

Unknown arguments are ignored. Invalid, missing, negative, or overflowing delay values retain
the current setting. A zero load delay is supported.

## Interactions

- Sign in with `admin` / `secret` for `Welcome, admin`; other credentials produce `Invalid credentials`.
- Remember me reports `Remember: True` or `Remember: False`. Panel A/B have duplicate OK buttons
  reporting `A OK` and `B OK`, respectively.
- Load disables itself and reports `Loading...`, then reveals Data loaded, enables Continue, and
  reports `Loaded`. Continue reports `Continued`.
- Choose Red, Green, or Blue for `Color: <color>`. Select a list item for `Selected: Item N`.
- The list contains 500 strings. The read-only grid contains 200 products with columns Id, Name,
  and Qty; selecting a row reports `Row: Product N`. Both controls retain WPF virtualization.
- Open dialog opens an owned modal window titled `WTK Demo - Dialog`. Save reports `Note: <text>`;
  Cancel or closing it reports `Note cancelled`.
- Show message opens a native message box titled `WTK Demo Message`, with `Hello from demo`.
  Dismissing it reports `Message closed`. Help > About shows `WTK Demo 1.0`.
- File > Reset clears credentials, checkbox, and selections, cancels a pending load, restores
  initial async controls, and reports `Ready`. File > Exit closes the app.

## UI Automation observations

Checked on Windows using the accessibility tree and Microsoft Windows SDK Inspect. The role,
Name, and AutomationId columns below are observed accessibility values; the helper normalizes
role labels (for example, List appears as `list view`). ClassName values marked `*` are the
expected WPF/Win32 provider classes from the controls, not individually verified raw properties.
Inspect directly confirmed the main window as Window/Window/WPF and a list text child as
Text/TextBlock/WPF. Other framework values remain expected provider values.

| Element | Observed role | ClassName | Name | AutomationId | FrameworkId |
|---|---|---|---|---|---|
| Main window | window | `Window` | `WTK Demo` | empty | WPF |
| Menu bar | menu | `Menu`* | empty | empty | WPF* |
| File | menu item | `MenuItem`* | `File` | empty | WPF* |
| Credentials | group | `GroupBox`* | `Credentials` | empty | WPF* |
| Username box | edit | `TextBox`* | empty | empty | WPF* |
| Password box | edit | `PasswordBox`* | empty | empty | WPF* |
| Remember me | check box | `CheckBox`* | `Remember me` | empty | WPF* |
| Sign in | button | `Button`* | `Sign in` | empty | WPF* |
| Panel A / B OK | button | `Button`* | `OK` | empty | WPF* |
| Data loaded | text | `TextBlock`* | `Data loaded` | empty | WPF* |
| Color combo | combo box | `ComboBox`* | empty | `ColorCombo` | WPF* |
| Items list | list view | `ListBox`* | empty | empty | WPF* |
| List item | list item | `ListBoxItem`* | `Item N` | empty | WPF* |
| List text child | text | `TextBlock` | `Item N` | empty | WPF |
| Products grid | datagrid | `DataGrid`* | empty | empty | WPF* |
| Grid row | dataitem | `DataGridRow`* | `DemoApp.Product` | empty | WPF* |
| Grid cell | data grid cell | `DataGridCell`* | cell text | empty | WPF* |
| Status text | text | `TextBlock`* | current status | `StatusText` | WPF* |
| Note dialog | window | `Window`* | `WTK Demo - Dialog` | empty | WPF* |
| Message box | dialogue | `#32770`* | `WTK Demo Message` | empty | Win32* |
| Message box OK | button | `Button`* | `OK` | `2` | Win32* |

Only StatusText and ColorCombo are explicitly assigned application IDs. Window chrome exposes
`MenuBar`; DataGrid templates expose `PART_ColumnHeadersPresenter` and header/row gripper IDs.
The status bar adds an outer text peer with the same status name but no ID. Buttons also expose
text children matching their names. Use the ID to select the actual status TextBlock.
Collapsed Data loaded is absent until Load completes. Scrolling the list to Item 500 realizes
the final items without exposing all 500 at once. Grid row names intentionally remain
`DemoApp.Product` because Product does not override ToString.

## Verification record

Release build succeeds with zero warnings and errors. Desktop checks covered valid/invalid
login, both checkbox states, duplicate OK buttons, default and zero-delay loading, Continue, color/list/grid selection,
Item 500 virtualization, empty-note Save, Cancel, message dismissal, Reset, About, custom title,
unknown argument handling, and File > Exit (exit code 0). Slow-start was exercised with 800 ms,
but its exact elapsed duration was not measured.

The automation helper could display and click the owned note dialog but did not reliably direct
typed text into it; nonempty-note Save still needs a manual check. Inspect runs at a higher
integrity level than the helper, so the remaining raw ClassName/FrameworkId properties should
be checked directly in Inspect before treating them as a fully verified engine contract.

`examples/demo-tests/pyproject.toml` points at this Release executable and activates the extension
development workspace. The config loader and functional example tests are later implementation
tasks; the current Python CLI only prints its version.
