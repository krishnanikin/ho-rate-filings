#################################################################################
# GLOBALS                                                                       #
#################################################################################

PROJECT_NAME = ho-rate-filings
PYTHON_VERSION = 3.11
PYTHON_INTERPRETER = python

#################################################################################
# COMMANDS                                                                      #
#################################################################################


## Install Python dependencies
.PHONY: requirements
requirements:
	$(PYTHON_INTERPRETER) -m pip install -U pip
	$(PYTHON_INTERPRETER) -m pip install -r requirements.txt
	



## Delete all compiled Python files
.PHONY: clean
clean:
	find . -type f -name "*.py[co]" -delete
	find . -type d -name "__pycache__" -delete


## Lint using ruff (use `make format` to do formatting)
.PHONY: lint
lint:
	ruff format --check
	ruff check

## Format source code with ruff
.PHONY: format
format:
	ruff check --fix
	ruff format



## Run tests
.PHONY: test
test:
	python -m pytest tests


## Set up Python interpreter environment
.PHONY: create_environment
create_environment:
	@bash -c "if [ ! -z `which virtualenvwrapper.sh` ]; then source `which virtualenvwrapper.sh`; mkvirtualenv $(PROJECT_NAME) --python=$(PYTHON_INTERPRETER); else mkvirtualenv.bat $(PROJECT_NAME) --python=$(PYTHON_INTERPRETER); fi"
	@echo ">>> New virtualenv created. Activate with:\nworkon $(PROJECT_NAME)"
	



#################################################################################
# PROJECT RULES                                                                 #
#################################################################################


## Download raw data (TX/FL/CA filings, FEMA, NOAA, FHFA, FRED, FIO) into data/raw
.PHONY: data
data:
	$(PYTHON_INTERPRETER) -m ho_rate_filings.dataset download
	$(PYTHON_INTERPRETER) -m ho_rate_filings.dataset process

## Build analysis tables in data/processed
.PHONY: features
features:
	$(PYTHON_INTERPRETER) -m ho_rate_filings.features

## Fit COVID-period, disaster/housing, event-study and break models (models/)
.PHONY: train
train:
	$(PYTHON_INTERPRETER) -m ho_rate_filings.modeling.train

## Render static figures to reports/figures
.PHONY: plots
plots:
	$(PYTHON_INTERPRETER) -m ho_rate_filings.plots

## Run the full pipeline: data -> features -> train -> plots
.PHONY: pipeline
pipeline: data features train plots

## Launch the Streamlit dashboard
.PHONY: dashboard
dashboard:
	streamlit run dashboard/app.py


#################################################################################
# Self Documenting Commands                                                     #
#################################################################################

.DEFAULT_GOAL := help

define PRINT_HELP_PYSCRIPT
import re, sys; \
lines = '\n'.join([line for line in sys.stdin]); \
matches = re.findall(r'\n## (.*)\n[\s\S]+?\n([a-zA-Z_-]+):', lines); \
print('Available rules:\n'); \
print('\n'.join(['{:25}{}'.format(*reversed(match)) for match in matches]))
endef
export PRINT_HELP_PYSCRIPT

help:
	@$(PYTHON_INTERPRETER) -c "${PRINT_HELP_PYSCRIPT}" < $(MAKEFILE_LIST)
