# module entry

import sys


def _repair_protocol():
    # runs without Qt: a stale handler can be fixed from any interpreter
    from .platform import ensure_registered
    command = ensure_registered(force=True)
    print("dreamSort protocol registered: %s" % (command or "(failed)"))
    return 0 if command else 1


def _main():
    if "--register-protocol" in sys.argv[1:]:
        return _repair_protocol()
    from .main import main
    return main()


if __name__ == "__main__":
    sys.exit(_main())
