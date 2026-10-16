# Match UI Automation properties

Use `where={...}` on `Element`, typed elements, `Elements` and `Window`. Every entry must
match, alongside the usual `name=`, `automation_id=`, `class_name=` and scoping options.
Strings are exact; compiled regular expressions use `re.search`. Boolean and numeric properties
need actual booleans and numbers, not their string representations.

```python
# pseudo-code
import re
from wintestkit import Button, Element, Window

save = Button(where={"HelpText": "Save", "IsEnabled": True})
address = Element(where={"ItemStatus": re.compile(r"\.AddressBox$")})
dialog = Window(where={"FrameworkId": "WPF", "ItemStatus": "Company.Views.AddressDialog"})
```

Property names are case-sensitive UIA names, such as `HelpText`, `ItemStatus`, `ItemType`,
`IsPassword`, `HasKeyboardFocus`, `ProcessId` and `GridRowCount`. `Value` is shorthand for
`ValueValue`. `ControlType` accepts a control type name (such as `"Button"`) or a regex.
Scalar properties in WinTestKit's UIA property registry are supported; element references, arrays,
points and rectangles are not `where` matchers. A provider must actually expose the property.
Unknown names, invalid types and duplicate properties produce errors rather than silent fallbacks.
Do not specify the same property through both a keyword and `where`, or through two aliases.

## TestComplete property names

Aliases rename an existing UIA property; they do not make private .NET properties readable.
Put shared aliases in `wintestkit.yaml`:

```yaml
property_aliases:
  ClrFullClassName: ItemStatus
```

Then `Element(where={"ClrFullClassName": "Company.Controls.AddressBox"})` matches the control's
`ItemStatus`. The application must first expose that full type name there. Aliases merge across
project TOML, shared YAML, local TOML, local YAML and overrides; later definitions win per alias.
An alias cannot shadow a real UIA property, and alias chains are not supported.

## Expose full WPF type names in test builds

Install this helper before creating any windows, for example from `App.OnStartup`. Define the
`UITEST` compilation symbol only in the build used for automation, then call
`TestAutomationProperties.Install()`. The loaded-event handler also covers controls loaded later,
including realized virtualized controls; it does not create unrealized controls.

```csharp
using System;
using System.Windows;
using System.Windows.Automation;

internal static class TestAutomationProperties
{
    public static void Install()
    {
#if UITEST
        EventManager.RegisterClassHandler(typeof(FrameworkElement), FrameworkElement.LoadedEvent,
            new RoutedEventHandler((sender, args) =>
            {
                if (sender is FrameworkElement control && ReferenceEquals(args.Source, control)
                    && string.IsNullOrEmpty(AutomationProperties.GetItemStatus(control)))
                    AutomationProperties.SetItemStatus(control,
                        control.GetType().FullName ?? control.GetType().Name);
            }), true);
#endif
    }
}
```

Do not overwrite meaningful accessibility metadata. This helper preserves an existing `ItemStatus`;
if your app uses that property, expose the test identifier through another suitable property or a
custom automation peer and change the alias. Custom peers may override the attached property's
value, so verify the actual UIA result. This app-side sample has not been exercised against a WPF
application in this development environment.

## Inspect before matching

```powershell
wtk inspect --depth 8
wtk inspect --at 400,300 --json
```

Text and JSON inspection include `HelpText`, `ItemStatus`, `ItemType` and configured alias
values when readable. Spy shows these on selection; its full-properties view reads the remaining
UIA properties. Confirm values rather than guessing from a TestComplete NameMapping. For example,
`ClrFullClassName` is not the same as UIA `ClassName`, which is commonly only a short name.
