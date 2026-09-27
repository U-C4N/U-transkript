"""Pure building blocks: parsing, selection and formatting without any I/O.

Nothing in this package may touch the network, subprocesses, threads or the clock; reading the
package's own data files is the only file access allowed. ``tests/test_architecture.py``
enforces this.
"""
