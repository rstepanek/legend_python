#!/usr/bin/env python
from distutils.core import setup

setup(name='Legend',
      version='0.1',
      description='Actor based ground truth modelling.',
      author='Ryan Stepanek',
      author_email='ryanstepanek@gmail.com',
      url='https://example.com/',
      packages=['data_loader', 'datastructs','system_configs','systems','utilities'],
      scripts = ["main.py"]
      )