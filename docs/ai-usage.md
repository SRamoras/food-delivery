# AI usage

## Dev container build failure

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** diagnosing why the dev container would not open; `.devcontainer/Dockerfile`, `.devcontainer/compose.devcontainer.yml`
- **Outcome:** kept. The base image's Yarn apt repo has no valid GPG key, so `apt-get update` failed while installing the `docker-outside-of-docker` feature. The repo is now removed before the feature is installed.
- **Verification:** ran `devcontainer up` with the dev container CLI on a temporary copy of the repo (databases healthy, `uv sync` finished, Python imports and the Docker CLI worked inside the container), then `docker compose config` and a build of the `workspace` service in the repo itself.
- **Mistakes caught:** none in the fix. The first test run failed because it used the system's Node v12, so it was repeated with the Node from the VS Code Server.
