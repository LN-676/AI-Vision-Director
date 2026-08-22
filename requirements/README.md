# Deployment requirements

`pyproject.toml` is the canonical dependency declaration for the Python package.
The files in this directory contain workload-specific cloud dependencies used by
the container builds. Root `requirements.txt` remains the convenient full local
installation list and must stay synchronized with the main project dependencies.
