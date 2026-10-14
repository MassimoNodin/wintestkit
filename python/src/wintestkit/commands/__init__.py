"""Sub-commands of the `wtk` command-line interface.

Every module defines ``add_parser(subparsers)`` and a ``run(args) -> int`` function. Modules keep
their top-level imports light (argparse only) so that `wtk --help` and `wtk --version` stay fast;
heavy imports happen inside ``run``.
"""
