"""Runtime-owned autonomous computer-agent components.

Import concrete components from their defining modules.  Keeping package import
side-effect free prevents the learning and task-engine modules from recursively
importing each other during startup.
"""
