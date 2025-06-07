from setuptools import setup, find_packages

setup(
    name="blocscape",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "cantera",
        "dash",
        "dash-cytoscape",
        "dash-core-components",
        "dash-html-components",
        "numpy",
        "pandas",
        "plotly",
    ],
    extras_require={
        "dev": [
            "pytest",
            "pytest-cov",
            "pre-commit",
            "ruff",
            "mypy",
            "sphinx",
            "sphinx-rtd-theme",
        ],
        "docs": [
            "sphinx",
            "sphinx-rtd-theme",
        ],
    },
    python_requires=">=3.11",
) 