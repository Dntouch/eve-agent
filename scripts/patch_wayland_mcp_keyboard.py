#!/usr/bin/env python3
"""Apply the reviewed, version-checked local keyboard fix in the isolated venv."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SHA = 'fc908e3dbb8f718f3feb690546e625ab2fdd23f54959861f3ca952c8e3864bf7'
distribution = importlib.metadata.distribution('wayland-mcp-kurojs')
if distribution.version != '0.6.1':
    raise SystemExit('Patch applies only to upstream version 0.6.1')
target = Path(distribution.locate_file('wayland_mcp/backends/input_portal.py')).resolve()
expected = (ROOT / '.venv-wayland-mcp').resolve()
if not target.is_relative_to(expected):
    raise SystemExit('Refusing to modify anything outside the isolated project venv')
original = target.read_bytes()
if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
    raise SystemExit('Original source hash mismatch; refusing to patch modified or different source')
source = original.decode().replace('\r\n', '\n')
start = source.index('    def type_text(self, text) -> bool:')
end = source.index('    def _keysym(self, symbol, state):', start)
replacement = '''    # EVE local variant: portal-keymap-v1; original package version 0.6.1.
    def type_text(self, text) -> bool:
        from .portal_keymap import PortalKeymap
        keymap = PortalKeymap()
        encoded = []
        for char in text:
            symbol = keysym_for_char(char)
            if symbol is None:
                raise ValueError(f"No keysym for character {char!r}")
            entry = keymap.character(char) or keymap.symbol(symbol)
            if entry is None:
                raise ValueError(f"Character U+{ord(char):04X} is not representable in the active compositor keymap; no text was sent")
            code, mask = entry
            encoded.append((keymap.modifiers(mask), code))
        self._ensure_session()
        for modifiers, code in encoded:
            self._tap_keycodes(modifiers, code)
        return True

    def press_key(self, key) -> bool:
        from .portal_keymap import PortalKeymap
        keymap = PortalKeymap()
        modifiers, main = parse_keysym_combo(key)
        main_entry = keymap.symbol(main)
        modifier_entries = [keymap.symbol(symbol) for symbol in modifiers]
        if main_entry is None or any(entry is None for entry in modifier_entries):
            raise ValueError("Key combination is not representable in the active compositor keymap; no key was sent")
        code, mask = main_entry
        codes = [entry[0] for entry in modifier_entries]
        codes.extend(modifier for modifier in keymap.modifiers(mask) if modifier not in codes)
        self._ensure_session()
        self._tap_keycodes(codes, code)
        return True

    def _tap_keycodes(self, modifiers, code):
        held = []
        main_attempted = False
        try:
            for modifier in modifiers:
                # Release even if the response is lost after the portal applied
                # the event. No success is inferred from an exception.
                held.append(modifier)
                self._keycode(modifier, 1)
            main_attempted = True
            self._keycode(code, 1)
        finally:
            try:
                if main_attempted:
                    self._keycode(code, 0)
            finally:
                failure = None
                for modifier in reversed(held):
                    try:
                        self._keycode(modifier, 0)
                    except Exception as exc:
                        failure = exc
                if failure is not None:
                    raise failure

    def _keycode(self, code, state):
        from gi.repository import GLib
        self._notify("NotifyKeyboardKeycode",
            GLib.Variant("(oa{sv}iu)", (self._handle, {}, int(code), state)))

    def _tap_keysym(self, modifiers, symbol):
        held = []
        try:
            for modifier in modifiers:
                held.append(modifier)
                self._keysym(modifier, 1)
            try:
                self._keysym(symbol, 1)
            finally:
                self._keysym(symbol, 0)
        finally:
            failure = None
            for modifier in reversed(held):
                try:
                    self._keysym(modifier, 0)
                except Exception as exc:
                    failure = exc
            if failure is not None:
                raise failure

'''
patched = source[:start] + replacement + source[end:]
backup = target.with_suffix('.py.upstream-0.6.1')
backup.write_bytes(original)
target.write_text(patched)
helper = ROOT / 'patches/wayland-mcp-kurojs/portal_keymap.py'
shutil.copyfile(helper, target.with_name('portal_keymap.py'))
manifest = {'variant': '0.6.1+eve.portal-keymap-v1', 'upstream_sha256': ORIGINAL_SHA,
            'patched_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
            'target': str(target), 'pywayland_version': importlib.metadata.version('pywayland')}
(ROOT / 'docs/WAYLAND-MCP-KEYBOARD-PATCH.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
