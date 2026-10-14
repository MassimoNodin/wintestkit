import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "out/**", ".vscode-test/**"] },
  ...tseslint.configs.recommended,
);
