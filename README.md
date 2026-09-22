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

## GitHub caveat

While the component repositories are private on GitHub, neither half of this setup
works there, and all three failures were reproduced on the organisation:

* a reusable workflow living in a private repository cannot be called — the run
  ends in `startup_failure` before any job starts, even with the repository's
  Actions access set to `organization`;
* the default `GITHUB_TOKEN` reaches its own repository only, so checking out this
  repository as a submodule fails with `remote: Repository not found`;
* for the same reason `transaction-engine` cannot fetch its sibling components, and
  its standalone build dies with `fatal: Could not read from remote repository`.

So on GitHub every component carries a self-contained build-and-test workflow and
`transaction-engine` runs only on demand. GitLab has neither limitation: a job token
reaches sibling projects of the same group, subject to the project's job-token
allowlist, which has to be set for `transaction-engine`.
