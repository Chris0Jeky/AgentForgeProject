PY ?= python3

.PHONY: install test lint build clean

install:
	$(PY) -m pip install -e .

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m compileall agentforge

build:
	$(PY) -m pip install --upgrade build
	$(PY) -m build

clean:
	rm -rf dist build *.egg-info
