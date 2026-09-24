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
| `third_party/googletest` | used by the GitLab build jobs only, through `FETCHCONTENT_SOURCE_DIR_GOOGLETEST` — see below |

The submodule is a development-time dependency only: a component's
`CMakeLists.txt` never refers to it, so a consumer that adds the component as a
submodule does not need `--recursive`.

## Pinning

A component pins this repository twice — the `ref:` of the CI include and the
submodule commit. Keep them on the same tag: a pipeline running the template
from one version against configs from another is the drift this repository
exists to prevent.

## googletest copy

The GitLab runner cannot reach GitHub reliably: cloning googletest failed with
`Connection reset by peer` on every build job of the first hwlib pipelines. The
GitLab build jobs therefore pass
`-DFETCHCONTENT_SOURCE_DIR_GOOGLETEST=${CI_PROJECT_DIR}/ci-shared/third_party/googletest`,
and FetchContent uses this copy instead of downloading. Local builds and the
GitHub workflow still download googletest as the components declare it.

`third_party/googletest` is googletest v1.15.2 (commit `b514bdc`) without its
`.git` directory, unmodified, under its own BSD-3-Clause `LICENSE`. It must stay
on the same version as the `GIT_TAG` in the components' `CMakeLists.txt`,
otherwise CI tests against a different googletest than developers do. To update:

    git clone --depth 1 --branch <tag> https://github.com/google/googletest.git /tmp/gt
    rsync -a --delete --exclude=.git /tmp/gt/ third_party/googletest/

then change the `GIT_TAG` in every component and the version above together.

## Sibling components in CI

`settings-record` and `transaction-engine` fetch other components over HTTPS
from `HWLIB_REMOTE`. The build jobs rewrite `https://${CI_SERVER_HOST}/` to carry
the job token, so the clone authenticates as the running job. For that to be
allowed, each fetched project (`crc`, `bit-ops`, `dedup-cache`) must list the
dependant in Settings → CI/CD → Job token permissions; setting it needs the
Maintainer role on the fetched project.

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
