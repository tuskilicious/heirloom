"""
Whether a controller reaches the real window: makes a virtual one with Linux's uinput, presses A, and asks the page.
Needs /dev/uinput and the window from window_probe.py running.
    python tests/virtual_pad.py <port>
"""
import json
import sys
import time

from evdev import AbsInfo, UInput, ecodes
from window_probe import Page, page_socket

CAPABILITIES = {
    ecodes.EV_KEY: [ecodes.BTN_SOUTH, ecodes.BTN_EAST, ecodes.BTN_NORTH, ecodes.BTN_WEST, ecodes.BTN_TL, ecodes.BTN_TR,
                    ecodes.BTN_SELECT, ecodes.BTN_START, ecodes.BTN_MODE],
    ecodes.EV_ABS: [(axis, AbsInfo(0, -32768, 32767, 16, 128, 0))
                    for axis in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY)],
}
READ = "[...navigator.getGamepads()].filter(Boolean).map((p) => ({id: p.id, pressed: p.buttons.map((b) => b.pressed)}))"


def main() -> None:
    page = Page(page_socket(int(sys.argv[1]), 60))
    with UInput(CAPABILITIES, name='Xbox 360 Controller', vendor=0x045e, product=0x028e, version=0x110) as pad:
        for _ in range(30):
            pad.write(ecodes.EV_KEY, ecodes.BTN_SOUTH, 1)
            pad.syn()
            time.sleep(0.25)
            seen = page.evaluate(READ)
            pad.write(ecodes.EV_KEY, ecodes.BTN_SOUTH, 0)
            pad.syn()
            time.sleep(0.25)
            if seen and any(True in p['pressed'] for p in seen):
                print('controller reached the page:', json.dumps(seen))
                return
        print('controller never reached the page:', json.dumps(page.evaluate(READ)))
        sys.exit(1)


if __name__ == '__main__':
    main()
