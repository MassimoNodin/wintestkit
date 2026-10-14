# WinTestKit

UI test automation for Windows WPF applications.

This extension scaffold contributes the planned WinTestKit commands, Elements tree, and Spy
panel. Only Show Output is functional; other commands log that they are not implemented.
The Python UI Automation engine and editor integrations will be added in later tasks.

## Development

Run `npm ci`, then `npm run build`, `npm run typecheck`, `npm run lint`, and `npm test`.
Use the repository's Run Extension launch configuration for an Extension Development Host.
`npm run test:integration` downloads an isolated VS Code host and installs its Python extension.
`npm run package` builds a Windows x64 VSIX in `dist/`.
Protocol generation (`npm run gen:types`) requires the schemas added in T0.5.
