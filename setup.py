from setuptools import setup, find_packages
import os
import re

# README dosyasını oku
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# Requirements dosyasını oku
def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]

# Version'u src/__init__.py'den oku
def read_version():
    with open(os.path.join("src", "__init__.py"), "r", encoding="utf-8") as fh:
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', fh.read(), re.MULTILINE)
        if match:
            return match.group(1)
        raise RuntimeError("Unable to find version string in src/__init__.py")

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
            "responses>=0.20.0",
            "freezegun>=1.2.0",
            "black>=21.0",
            "flake8>=3.8",
            "mypy>=0.800",
        ],
        "docs": [
            "sphinx>=4.0",
            "sphinx-rtd-theme>=1.0",
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
