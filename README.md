# autojigger https://github.com/daceto447/autojigger.git

[![Build](https://github.com/LavLabInfrastructure/python-template/actions/workflows/build.yml/badge.svg)](https://github.com/LavLabInfrastructure/python-template/actions/workflows/build.yml)
[![Tests](https://github.com/LavLabInfrastructure/python-template/actions/workflows/pytest.yml/badge.svg)](https://github.com/LavLabInfrastructure/python-template/actions/workflows/pytest.yml)
[![Lint](https://github.com/LavLabInfrastructure/python-template/actions/workflows/pylint.yml/badge.svg)](https://github.com/LavLabInfrastructure/python-template/actions/workflows/pylint.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/python-template.svg)](https://pypi.org/project/python-template)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/python-template.svg)](https://pypi.org/project/python-template)

-----

A tool to generate a 3D model of a slicer jig from a NIfTI mask, supporting customizable profiles. 

## What's Included

| Feature | Tool |
|---------|------|
| Build & environments | [Hatch](https://hatch.pypa.io/) with [hatch-pip-compile](https://github.com/juftin/hatch-pip-compile) |
| Linting & formatting | [Ruff](https://docs.astral.sh/ruff/) |
| Testing | [pytest](https://docs.pytest.org/) + [coverage](https://coverage.readthedocs.io/) |
| Type checking | [mypy](https://mypy.readthedocs.io/) |
| Documentation | [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) + [mkdocstrings](https://mkdocstrings.github.io/) |
| Containerization | Multi-stage [Dockerfile](./Dockerfile) (dev / hatch / prod) |
| CI/CD | [GitHub Actions](./.github/workflows/) with Dependabot |
| Dev environment | [Dev Container](./.devcontainer/) for VS Code / Codespaces |
| Git hygiene | [pre-commit](./.pre-commit-config.yaml) hooks |


## Installation

**Prerequisites:** Python 3.10+ and [Hatch](https://hatch.pypa.io/latest/install/).

## Usage

### CLI

```
hatch run python src/autojigger/autojigger.py <OPTIONS>
```

### Options

```-h, --help```: display help message

```-i, --nifti_path <path>```: path to NIfTI input

```-o, --jig_path <path>```: path to STL output of jig

```-m, --mold_path <path> (optional)```: path to STL output of organ mold

```-p, --profile <profile>```: profile name key from profile dict

```-j, --profile_path <path> (optional)```: path to custom profile json/yaml

### Batch Jig Creation

To run the script on a directory of masks, run:

```
./src/autojigger/batch_jig.sh <NIfTI directory> <output directory> (<profile>)
```

Without an added profile argument, the script will get the profile from the filename before the first underscore (e.g. "brain_mask.nii.gz" -> "brain").

## Profile Configuration

Enter custom profiles into `src/autojigger/profiles.json`, following the format of the default profiles.

### Specifications:

`organ` sets the organ type, needed for some settings.

`x/y/z_wall` sizes the margins of the jig bordering the mold and cuts.

`pre/post_knife_space` add further margins on the y-axis.

`knife_width` controls the z-height of the gaps.

`min_slice_thickness` sets a minimum slice thickness. If above zero, and the MRI slices are smaller, the jig slice size and number of slices will be adjusted to meet the minimum.

`surface_label` controls the index for surface generation from the NIfTI; default is 1.

`mold_smoothing` controls the number of smoothing iterations to run on the organ mold.

`mold_decimation` controls the decimation, or polygon reduction, on the organ mold. The value determines the fraction of the original polygons to remove (i.e. increasing closer to 1.0 reduces more complexity).

`jig_offset` controls the starting point on the y-axis of the mold inside the jig. Increasing this leaves more space in the back of the jig.

`jig_steps` controls the number of times the mold is stepped forward and cut out the jig. Because this script forms a composite mold to cut out of the jig one time for the sake of smoothing, increasing the steps above ~70 can cause manifold surface issues and break the geometry.

`jig_smoothing` controls the smoothing iterations for the composite mold that is cut out of the jig. These make the cuts inside the jig more smooth. While increasing this reduces the jaggedness of the mold cut-outs, it does not seem to reduce 3D-printing time.

`scale` controls the scale factor of the mold. The size of the jig is determined by the size of the mold, so this will determine the size of the end product. The default is 1.02 so that the mold is slightly larger than the actual organ.

`rotate_z` controls degree rotation about the z-axis. For simplicity, the program assumes that the slices in the input NIfTI are oriented axially(?), i.e. orthogonal to the z-axis.

`tumor_laterality` is either `"L"` or `"R"` to control which side of the organ faces out of the jig.


### Hatch Commands

Run these directly or use the provided [`Makefile`](./Makefile) shortcuts (e.g. `make test`, `make lint`).

| Task | Command |
|------|---------|
| Run tests | `hatch run test:test` |
| Tests + coverage | `hatch run test:cov` |
| Lint | `hatch run lint:check` |
| Format | `hatch run lint:format` |
| Auto-fix lint | `hatch run lint:fix` |
| Format + fix + lint | `hatch run lint:all` |
| Type check | `hatch run types:check` |
| Build docs | `hatch run docs:build-docs` |
| Serve docs | `hatch run docs:serve-docs` |
| Build wheel | `hatch build` |
| Clean artifacts | `make clean` |

### Docker

To run tests via Docker:
```
docker build --target hatch -t myapp:hatch .
docker run --rm -e HATCH_ENV=test myapp:hatch cov
```

To build production image (just the installed wheel):
```
docker build --target prod -t myapp:prod .
```

## Project Structure

```text
autojigger/
├── src/
│   └── autojigger/        # Package source
│       ├── __init__.py          # Public API & version export
│       ├── __about__.py         # Version string
│       ├── autojigger.py      # Main autojigger script
│       ├── profiles.json        # Configuration profiles for autojigger
│       ├── batch_jig.sh         # Script to run autojigger on a directory of NIfTIs
│       └── py.typed             # PEP 561 marker
├── tests/
│   ├── conftest.py              # Shared pytest fixtures
│   └── test_geometry.py         # Test validity of mold and jig geometry
├── docs/                        # MkDocs source files
├── requirements/                # Locked deps (auto-generated by hatch-pip-compile)
├── .devcontainer/               # Dev container config
├── .github/
│   ├── workflows/               # CI workflows (build, test, lint)
│   └── dependabot.yml           # Auto-update deps + actions + Docker
├── pyproject.toml               # All project & tool configuration
├── Dockerfile                   # Multi-stage build
├── Makefile                     # Dev shortcuts
├── mkdocs.yml                   # Docs config
├── .pre-commit-config.yaml      # Pre-commit hooks
├── .editorconfig                # Editor consistency
└── .gitignore
```

## License

`autojigger` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
