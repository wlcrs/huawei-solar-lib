import re

from setuptools import setup

with open("src/huawei_solar/__init__.py", "r") as fd:
    version = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', fd.read(), re.MULTILINE
    ).group(1)

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="huawei-solar",
    version=version,
    author="Emil Vanherp",
    author_email="emil@vanherp.me",
    description="A Python wrapper for the Huawei Inverter modbus TCP API",
    license="MIT License",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://gitlab.com/EmilV2/huawei-solar",
    install_requires=["git+https://github.com/Emilv2/pymodbus@3bdb32", "pytz>=2019.3"],
    python_requires=">=3.6",
    packages=["huawei_solar"],
    package_dir={"": "src"},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
