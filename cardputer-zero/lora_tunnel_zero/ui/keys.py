"""Keyboard input from Linux evdev, mapped to logical keys.

The CardputerZero's TCA8418 keyboard appears as an input device. As on the
Cardputer ADV, ; . , / double as Up, Down, Left, Right, and ` acts as Escape.
Text fields read characters directly instead of the arrow aliases.

The built-in keyboard's driver (tca8418_keypad_m5stack) sends its own codes
for the symbols typed with Sym, for example 70 for "_" and 71 for "-". Several
of those codes collide with standard PC keys (51 is "&" here, "," on a PC), so
the symbol table applies only to the built-in keyboard. It is the same table
the CardputerZero launcher uses, and the system's keymap file overrides it.
"""

import os
from pathlib import Path
import select
import struct

EVENT = struct.Struct("llHHi")
EV_KEY = 1

# linux/input-event-codes.h
CODES = {
    1: "ESC", 14: "BACKSPACE", 15: "TAB", 28: "ENTER", 57: "SPACE", 96: "ENTER",
    103: "UP", 108: "DOWN", 105: "LEFT", 106: "RIGHT", 102: "HOME", 107: "END",
    104: "PAGEUP", 109: "PAGEDOWN", 111: "DELETE",
    42: "SHIFT", 54: "SHIFT", 29: "CTRL", 97: "CTRL", 56: "ALT", 100: "ALT", 464: "FN",
}
CHARS = {
    2: "1!", 3: "2@", 4: "3#", 5: "4$", 6: "5%", 7: "6^", 8: "7&", 9: "8*", 10: "9(", 11: "0)",
    12: "-_", 13: "=+", 16: "qQ", 17: "wW", 18: "eE", 19: "rR", 20: "tT", 21: "yY", 22: "uU",
    23: "iI", 24: "oO", 25: "pP", 26: "[{", 27: "]}", 30: "aA", 31: "sS", 32: "dD", 33: "fF",
    34: "gG", 35: "hH", 36: "jJ", 37: "kK", 38: "lL", 39: ";:", 40: "'\"", 41: "`~", 43: "\\|",
    44: "zZ", 45: "xX", 46: "cC", 47: "vV", 48: "bB", 49: "nN", 50: "mM", 51: ",<", 52: ".>",
    53: "/?",
}
# Built-in keyboard Sym codes (CardputerZero launcher cp0_keyboard_keymap.c).
SYM_CHARS = {
    26: "!", 27: "@", 39: "#", 40: "$", 41: "%", 43: "^", 51: "&", 52: "*", 53: "(", 94: ")",
    55: "~", 69: "`", 70: "_", 71: "-", 72: "+", 73: "=", 74: "[", 75: "]", 76: "{", 77: "}",
    79: ";", 80: ":", 81: "'", 82: '"', 83: "<", 85: ">", 86: "\\", 89: "|", 90: ",", 91: ".",
    92: "/", 93: "?",
}
SYSTEM_KEYMAP = Path("/usr/share/keymaps/tca8418_keypad_m5stack_keymap.map")
# X keysym names for printable ASCII, as used in the system keymap file.
KEYSYMS = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "apostrophe": "'", "quoteright": "'",
    "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+", "comma": ",",
    "minus": "-", "period": ".", "slash": "/", "colon": ":", "semicolon": ";", "less": "<",
    "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_",
    "grave": "`", "quoteleft": "`", "braceleft": "{", "bar": "|", "braceright": "}",
    "asciitilde": "~",
}
for _n, _d in enumerate("0123456789"):
    KEYSYMS[_d] = _d
for _c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEYSYMS[_c] = _c


def parse_keymap(text):
    """Code to character from lines like "keycode 70 = underscore"; None if empty."""
    table = {}
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 4 and parts[0] == "keycode" and parts[2] == "=" and parts[1].isdigit():
            char = KEYSYMS.get(parts[3])
            if char is None and parts[3].startswith("U") and len(parts[3]) == 5:
                try:
                    char = chr(int(parts[3][1:], 16))
                except ValueError:
                    char = None
            if char:
                table[int(parts[1])] = char
    return table or None


def sym_chars(path=SYSTEM_KEYMAP):
    """The built-in keyboard's symbol table: the system keymap file, else the default."""
    try:
        return parse_keymap(Path(path).read_text()) or dict(SYM_CHARS)
    except (OSError, UnicodeDecodeError):
        return dict(SYM_CHARS)


def is_builtin(path):
    """True unless the input device is on USB or Bluetooth (an external keyboard)."""
    name = os.path.basename(os.path.realpath(path))
    try:
        bus = Path("/sys/class/input/%s/device/id/bustype" % name).read_text().strip()
    except OSError:
        return True
    return int(bus, 16) not in (0x03, 0x05)


ARROW_ALIASES = {";": "UP", ".": "DOWN", ",": "LEFT", "/": "RIGHT", "`": "ESC"}


class Key:
    """A key press: `name` is logical (UP, ENTER, A...), `char` is typed text."""

    __slots__ = ("name", "char", "repeat")

    def __init__(self, name, char="", repeat=False):
        self.name, self.char, self.repeat = name, char, repeat

    def __eq__(self, other):
        return self.name == other if isinstance(other, str) else NotImplemented

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return "Key(%r)" % self.name


def find_keyboards():
    """Input devices whose key bitmap includes letters, from /proc/bus/input/devices."""
    paths = []
    try:
        blocks = Path("/proc/bus/input/devices").read_text().split("\n\n")
    except OSError:
        return paths
    for block in blocks:
        handlers = next((l for l in block.splitlines() if l.startswith("H: Handlers=")), "")
        keybits = next((l for l in block.splitlines() if l.startswith("B: KEY=")), "")
        events = [h for h in handlers.split("=", 1)[-1].split() if h.startswith("event")]
        if not events or not keybits:
            continue
        words = keybits.split("=", 1)[1].split()
        bits = int("".join(w.rjust(16, "0") for w in words), 16) if words else 0
        if bits >> 30 & 1 and bits >> 16 & 1:  # KEY_A and KEY_Q
            paths.append("/dev/input/" + events[0])
    return paths


class EvdevInput:
    def __init__(self, paths=None):
        self.devices = []
        self.builtin = set()
        self.sym = sym_chars()
        for path in paths or find_keyboards():
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self.devices.append(fd)
            if is_builtin(path):
                self.builtin.add(fd)
        self.shift = self.fn = self.ctrl = False
        self.text_mode = False

    def poll(self, timeout):
        """Return a list of Keys pressed within `timeout` seconds."""
        if not self.devices:
            select.select([], [], [], timeout)
            return []
        ready, _, _ = select.select(self.devices, [], [], timeout)
        keys = []
        for fd in ready:
            try:
                data = os.read(fd, EVENT.size * 32)
            except (BlockingIOError, OSError):
                continue
            for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, kind, code, value = EVENT.unpack_from(data, offset)
                if kind != EV_KEY:
                    continue
                key = self.translate(code, value, fd in self.builtin)
                if key is not None:
                    keys.append(key)
        return keys

    def translate(self, code, value, builtin=True):
        name = CODES.get(code)
        if name in ("SHIFT", "FN", "CTRL"):
            setattr(self, name.lower(), value != 0)
            return None
        if name == "ALT":
            return None
        if value == 0:
            return None
        repeat = value == 2
        if builtin and code in self.sym:
            char = self.sym[code]
        elif code in CHARS:
            char = CHARS[code][1 if self.shift else 0]
        else:
            char = None
        if char:
            if not self.text_mode and (self.fn or not self.shift) and char in ARROW_ALIASES and not self.ctrl:
                return Key(ARROW_ALIASES[char], char, repeat)
            return Key(char.upper() if char.isalpha() else char, char, repeat)
        if name:
            return Key(name, " " if name == "SPACE" else "", repeat)
        return None

    def close(self):
        for fd in self.devices:
            try:
                os.close(fd)
            except OSError:
                pass


class ScriptedInput:
    """Feeds a fixed key sequence; used by tests and the screenshot renderer."""

    def __init__(self, names=()):
        self.queue = [Key(n, n.lower() if len(n) == 1 else (" " if n == "SPACE" else "")) for n in names]
        self.text_mode = False

    def push(self, *names):
        self.queue.extend(Key(n, n.lower() if len(n) == 1 else "") for n in names)

    def poll(self, timeout):
        return [self.queue.pop(0)] if self.queue else []

    def close(self):
        pass
