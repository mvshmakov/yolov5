from pathlib import Path
from setuptools import setup, find_packages

requirements = [
    l.strip() for l in open('requirements.txt').readlines()
    if not l.startswith('# ')
]

setup(
    name='yolo5',
    version='0.0.1',
    package_dir={'yolo5':'yolo5'},
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.8",
    include_package_data=True,
)
