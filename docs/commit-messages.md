# Commit messages

Every commit uses one format, so the history can be read at a glance and a release's changelog
can be written from it. This is [Conventional Commits](https://www.conventionalcommits.org/)
with a bullet-list body.

## Format

```
<type>(<scope>): <short description>

- Added/Fixed/Changed/Removed what changed and what it enables
- One bullet per change

<optional footer>
```

### Subject line

- Starts with a **type** from the table below, then an optional **scope** in brackets, a colon
  and a space.
- The description is **imperative and lowercase** ("add", not "added"), has **no full stop**, and
  is about 50 characters long and never over 72.
- It should complete the sentence "this commit will ...".

### Body

- Separated from the subject by one blank line.
- One bullet per change. Each bullet starts with a past-tense verb: **Added**, **Fixed**,
  **Changed**, **Removed** (or **Updated** for documentation).
- Where the reason is not obvious, end the bullet with it or add a bullet starting `Why:`.
- A trivial commit (a typo, formatting) needs no body.
- Wrap lines at about 72 characters and indent a wrapped bullet by two spaces.

### Footer

- `Closes: #12` or `Refs: #12` links an issue.
- `BREAKING CHANGE: <what breaks and how to migrate>` describes a breaking change.
- A `Co-Authored-By:` trailer, if there is one, goes last.

## Types

| Type | Use for | Changelog section |
| --- | --- | --- |
| `feat` | New behaviour users can see or use | Added |
| `fix` | A bug fix | Fixed |
| `perf` | A speed-up with no change in behaviour | Changed |
| `refactor` | Restructuring with no change in behaviour | none |
| `docs` | Documentation only | none |
| `test` | Tests only | none |
| `ci` | Workflows and automation | none |
| `build` | Packaging, dependencies and version bumps | none |
| `chore` | Anything else that users never see | none |
| `revert` | Undoing an earlier commit | none |

When one commit holds several kinds of change, use the type of the most important one and list
the rest in the body.

## Scopes

The scope is optional. Use it when a commit stays within one area, and leave it out when it
spans several.

| Scope | Area |
| --- | --- |
| `python` | The Python package in `python/` |
| `vscode` | The extension in `vscode/` |
| `spy` | The Spy view and its server methods |
| `schemas` | The shared JSON schemas |
| `docs` | The guides in `docs/` |
| `release` | Versions, changelog sections and the release workflow |

## Breaking changes

Add `!` after the type or scope and describe the break in a `BREAKING CHANGE:` footer:

```
feat(python)!: rename the suggest.locator RPC to inspect.locator

- Changed the method name and its schema

BREAKING CHANGE: extensions older than 0.2.0 can no longer request
suggested locators; upgrade both together.
```

## Examples

```
fix(spy): make Pick element work on elements without a runtime id

- Fixed every hover and pick failing on TeamViewer with "element has
  no runtime id"
- Changed picked elements to be keyed by their position below the
  nearest identifiable ancestor, matching tree expansion
- Changed hover to skip that lookup, which can take hundreds of ms
```

```
perf(python): list desktop windows with EnumWindows instead of UIA

- Changed Spy's "other apps" roots to use EnumWindows, which skips
  hidden windows of slow UI Automation providers
- Why: the UIA desktop walk took ~5.7 s on one machine; this takes 0.13 s
```

```
feat(spy): generate the suggested locator only on request

- Added a Generate suggested locator button with a spinner and a
  warning that large apps can take 20+ seconds
- Changed selection to load definitions and the preview without
  waiting for the locator
```

```
chore(release): prepare 0.1.1rc1
```

## Merges

Squash-merge a pull request and give the single commit a message in this format. Where a merge
commit is created instead, Git's default message ("Merge pull request #2 ...") is fine.

## Splitting commits

One commit should be one theme, so that it can be reviewed and reverted on its own. A change
that touches several areas is still one commit when the parts only make sense together, such
as a new server method with its schema, generated types and editor support. Unrelated changes
go in separate commits.
