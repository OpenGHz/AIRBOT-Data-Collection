"""Demo script for TkButtonPanelConfig 'script:' callback.

Prints a line every 0.3s and exits after a few iterations.
Handles SIGINT so the popup close can interrupt it.
"""

import signal
import sys
import time


_interrupted = False


def _handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True


def main() -> int:
    signal.signal(signal.SIGINT, _handle_sigint)

    for i in range(50):
        if _interrupted:
            print("SIGINT received, exiting...")
            return 130
        print(f"tick {i}")
        sys.stdout.flush()
        time.sleep(0.3)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
