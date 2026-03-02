# CI and quality for the AgentForge project

This repository ships with a lightweight CI pipeline:
- compile the package (`python -m compileall`)
- run unit tests (`python -m unittest -v`)

See `.github/workflows/ci.yml`.

## Local developer workflows

- `make test`
- `make lint` (compile-only; you can add ruff/mypy later)
- `make build`

## Future upgrades (optional)
- Add `ruff` for linting and formatting.
- Add `mypy` for stricter typing.
- Add integration tests that use a temporary git repo and mock `gh` calls.

AgentForge intentionally avoids heavy dependencies in v0.x to keep installation trivial.
