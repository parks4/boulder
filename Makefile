PROJECT := boulder
CONDA := conda
CONDAFLAGS :=
COV_REPORT := html

default: qa unit-tests type-check

qa:
	pre-commit run --all-files

unit-tests:
	python -m pytest -vv --cov=. --cov-report=$(COV_REPORT) --doctest-glob="*.md" --doctest-glob="*.rst" --ignore=tests/test_sim2stone/test_verification_upstream_physics.py

# Systematic verification: convert vendored Cantera example scripts through
# sim2stone + Boulder's runtime, then check the result against the *true*
# upstream script's own physics (not just "did the download run without
# crashing" -- see test_verification_upstream_physics.py's module docstring
# for the class of bug this catches that unit-tests alone missed).
verification-tests:
	python -m pytest -vv tests/test_sim2stone/test_verification_upstream_physics.py

type-check:
	python -m mypy . --exclude docs/cantera_examples

conda-env-update:
	$(CONDA) install -y -c conda-forge conda-merge
	$(CONDA) run conda-merge environment.yml ci/environment-ci.yml > ci/combined-environment-ci.yml
	$(CONDA) env update $(CONDAFLAGS) -f ci/combined-environment-ci.yml

template-update:
	pre-commit run --all-files cruft -c .pre-commit-config-cruft.yaml

docs-build:
	cd docs && rm -fr _api && make clean && make html

# DO NOT EDIT ABOVE THIS LINE, ADD COMMANDS BELOW
