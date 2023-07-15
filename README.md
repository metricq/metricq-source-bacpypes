![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)

# MetricQ BacNet source

Current limitations

- made by me... at 1am... what do I know, what the limitations are?

## Configuration

See [the pydantic model](metricq_source_bacpypes/config_model.py) for a description of the configuration.

## CI

- run all formatters and linters using tox as part of building the docker images
  - black
  - isort
  - mypy
  - flake8
- build docker images for all branches
- build docker images for version tags `vX.Y.Z`
- push docker images to ghcr.io/metricq
- **No** sphinx / documentation
- **No** upload to pypi
