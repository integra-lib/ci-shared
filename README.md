# ci-shared

Build tooling shared by every integra-lib component, so that eleven repositories
cannot drift into eleven different styles.

## What a component gets from here

| File | How it is consumed |
|---|---|
| `templates/component.yml` | the component's `.gitlab-ci.yml` includes it with `include: project:` — nothing is copied |
| `.github/workflows/component.yml` | the same pipeline for GitHub, called as a reusable workflow — also not copied |
| `.clang-format`, `.clang-tidy`, `.pre-commit-config.yaml` | symlinked from the component repository into the `ci-shared` submodule |
| `.releaserc.js`, `package.json`, `commitlint.config.js` | copied, because the tools read them from the repository root; the `config-check` job diffs the copies against this repository and fails on drift |

The submodule is a development-time dependency only: a component's
`CMakeLists.txt` never refers to it, so a consumer that adds the component as a
submodule does not need `--recursive`.

## Pinning

A component pins this repository twice — the `ref:` of the CI include and the
submodule commit. Keep them on the same tag: a pipeline running the template
from one version against configs from another is the drift this repository
exists to prevent.
