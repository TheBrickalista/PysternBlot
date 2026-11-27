# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

import sys


def parse_project_arg(argv: list[str]) -> str | None:
    """The project id given with --project ID / --project=ID, or None.

    Used by the Pyblication plugin's open_project() to open a given project;
    without it the app starts exactly as before."""
    for i, arg in enumerate(argv):
        if arg == "--project" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--project="):
            return arg.split("=", 1)[1] or None
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    from .selfcheck import parse_selfcheck_args, run_selfcheck
    requested, out_path = parse_selfcheck_args(argv)
    if requested:
        # Windowless: exits before Qt is imported or any QApplication exists.
        sys.exit(run_selfcheck(out_path))

    from .app import run
    project_id = parse_project_arg(argv)
    if project_id:
        run(project_id=project_id)
    else:
        run()

if __name__ == "__main__":
    main()
