# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    from .selfcheck import parse_selfcheck_args, run_selfcheck
    requested, out_path = parse_selfcheck_args(argv)
    if requested:
        # Windowless: exits before Qt is imported or any QApplication exists.
        sys.exit(run_selfcheck(out_path))

    from .app import run
    run()

if __name__ == "__main__":
    main()
