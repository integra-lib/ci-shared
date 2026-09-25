# ci-shared

Build tooling shared by every integra-lib component, so that eleven repositories
cannot drift into eleven different styles.

## What a component gets from here

| File | How it is consumed |
|---|---|
| `templates/component.yml` | the component's `.gitlab-ci.yml` includes it with `include: project:` — nothing is copied |
| `.github/workflows/component.yml` | the same pipeline for GitHub, called as a reusable workflow — also not copied |
| `.clang-format`, `.clang-tidy`, `.pre-commit-config.yaml` | symlinked from the component repository into the `ci-shared` submodule |
| `commitlint.config.js` | copied, because commitlint reads it from the repository root; the `config-check` job diffs the copy against this repository and fails on drift |
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

A component can prepare its build in `ci/before-build.sh`. The build jobs source
it after setting up git, so it can clone sources and append cmake arguments to
`CMAKE_EXTRA_ARGS`. The two dependants use it to build against a sibling's
review branch while the sibling's release tag does not exist yet.

## CI image

Every job runs in `${CI_REGISTRY_IMAGE}:arch`, an image in the component's own
registry built from `Dockerfile` here. The template's `docker` job builds and pushes
it; it is manual and offered on `main` only. A new component has no image until
someone runs that job once — until then its pipeline fails at the first job, pulling
the image.

## Versions and releases

There is no release job: a component's version is raised by hand, in the merge
request that changes it, and tagged after the merge.

1. The merge request raises `VERSION` in the `project()` call of `CMakeLists.txt` —
   the minor for a breaking change or a feature (before 1.0 a minor may break the
   API), the patch for a fix. Dependants check this number through the
   `HWLIB_VERSION` target property, so it must match the tag.
2. After the merge a Maintainer tags that commit on `main`:

       git tag -a vX.Y.Z -m vX.Y.Z <merge commit>
       git push origin vX.Y.Z

   Pushed tags start no pipeline.

A tag that disagrees with `VERSION` is a version check that lies to every dependant;
tag exactly what the merged `CMakeLists.txt` says.

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
