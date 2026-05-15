import os
import re

from setuptools import find_packages, setup


def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()


def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]


def read_version():
    with open(os.path.join("src", "__init__.py"), "r", encoding="utf-8") as fh:
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', fh.read(), re.MULTILINE)
        if not match:
            raise RuntimeError("Unable to find version string in src/__init__.py")
        return match.group(1)

setup(
    name="u-transkript",
    version=read_version(),
    author="U-C4N",
    author_email="noreply@deuz.ai",
    description="Extract YouTube transcripts and translate them with AI — standalone alternative to youtube-transcript-api",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/U-C4N/u-transkript",
    project_urls={
        "Documentation": "https://github.com/U-C4N/u-transkript/blob/main/README.md",
        "Source": "https://github.com/U-C4N/u-transkript/",
        "Tracker": "https://github.com/U-C4N/u-transkript/issues",
    },
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Education",
        "Intended Audience :: Science/Research",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Multimedia :: Video",
        "Topic :: Text Processing :: Linguistic",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.10",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "ruff>=0.8.0",
        ],
        "api": [
            "flask>=3.0",
        ],
    },
    keywords=[
        "youtube",
        "transcript",
        "translation",
        "ai",
        "gemini",
        "subtitle",
        "video",
        "nlp",
        "machine-learning",
        "automation"
    ],
    entry_points={
        'console_scripts': [
            'u-transkript=cli:main',
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
