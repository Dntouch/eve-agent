"""Translate the compositor's real keymap into authorized portal keycodes.

No synthetic keyboard layout, device access or private compositor API. This
module only reads wl_keyboard.keymap; injection stays with RemoteDesktop.
"""
import ctypes as C
import ctypes.util
import mmap
import os
import subprocess


def compositor_keymap():
    from pywayland.client import Display
    from pywayland.protocol.wayland import WlSeat

    result = {}
    seats, keyboards = [], []

    def keymap(_keyboard, format_, fd, size):
        try:
            if format_ != 1:
                raise RuntimeError('Unsupported compositor keymap format')
            with mmap.mmap(fd, size, access=mmap.ACCESS_READ) as memory:
                result['data'] = memory[:].rstrip(b'\0') + b'\0'
        finally:
            os.close(fd)

    def global_(_registry, name, interface, version):
        if interface == 'wl_seat' and not seats:
            seat = registry.bind(name, WlSeat, min(version, 7))
            seats.append(seat)
            keyboard = seat.get_keyboard()
            keyboards.append(keyboard)
            keyboard.dispatcher['keymap'] = keymap
            keyboard.dispatcher['modifiers'] = lambda _k, _serial, _depressed, _latched, _locked, group: result.update(group=group)

    display = Display()
    display.connect()
    try:
        registry = display.get_registry()
        registry.dispatcher['global'] = global_
        for _ in range(3):
            display.roundtrip()
        if 'data' not in result:
            raise RuntimeError('Compositor did not supply a keyboard keymap')
        return result
    finally:
        display.disconnect()


class PortalKeymap:
    def __init__(self):
        source = compositor_keymap()
        self.lib = lib = C.CDLL(ctypes.util.find_library('xkbcommon'))

        def function(name, result, *args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
            return fn

        ptr, u32 = C.c_void_p, C.c_uint32
        function('xkb_context_new', ptr, C.c_int)
        function('xkb_context_unref', None, ptr)
        function('xkb_keymap_new_from_string', ptr, ptr, C.c_char_p, C.c_int, C.c_int)
        function('xkb_keymap_unref', None, ptr)
        function('xkb_keymap_min_keycode', u32, ptr)
        function('xkb_keymap_max_keycode', u32, ptr)
        function('xkb_keymap_num_layouts', u32, ptr)
        function('xkb_keymap_num_layouts_for_key', u32, ptr, u32)
        function('xkb_keymap_num_levels_for_key', u32, ptr, u32, u32)
        function('xkb_keymap_key_get_syms_by_level', C.c_int, ptr, u32, u32, u32, C.POINTER(C.POINTER(u32)))
        function('xkb_keymap_key_get_mods_for_level', C.c_size_t, ptr, u32, u32, u32, C.POINTER(u32), C.c_size_t)
        function('xkb_keymap_mod_get_index', u32, ptr, C.c_char_p)
        function('xkb_keysym_to_utf32', u32, u32)
        context = lib.xkb_context_new(0)
        if not context:
            raise RuntimeError('Cannot allocate XKB context')
        keymap = None
        try:
            keymap = lib.xkb_keymap_new_from_string(context, source['data'], 1, 0)
            if not keymap:
                raise RuntimeError('Cannot parse compositor keymap')
            group = source.get('group')
            if group is None:
                if lib.xkb_keymap_num_layouts(keymap) == 1:
                    group = 0
                else:
                    # KDE's public layout query supplies the active group when
                    # wl_keyboard has not sent modifiers to this unfocused client.
                    query = subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.kde.keyboard',
                        '--object-path', '/Layouts', '--method', 'org.kde.KeyboardLayouts.getLayout'],
                        capture_output=True, text=True, timeout=5, check=True)
                    import re
                    found = re.fullmatch(r'\(uint32 (\d+),\)\s*', query.stdout)
                    if not found:
                        raise RuntimeError('Cannot determine active compositor keyboard layout')
                    group = int(found[1])
            if group >= lib.xkb_keymap_num_layouts(keymap):
                raise RuntimeError('Compositor keyboard layout index is invalid')
            self.group = group
            indexes = [(lib.xkb_keymap_mod_get_index(keymap, b'Shift'), 0xffe1),
                       (lib.xkb_keymap_mod_get_index(keymap, b'Mod5'), 0xfe03)]
            self.modifier_symbols = {1 << index: symbol for index, symbol in indexes if index < 32}
            allowed = sum(self.modifier_symbols)
            self.symbols, self.characters = {}, {}
            for code in range(lib.xkb_keymap_min_keycode(keymap), lib.xkb_keymap_max_keycode(keymap) + 1):
                layouts = lib.xkb_keymap_num_layouts_for_key(keymap, code)
                if not layouts:
                    continue
                layout = group if group < layouts else 0
                for level in range(lib.xkb_keymap_num_levels_for_key(keymap, code, layout)):
                    masks = (u32 * 64)()
                    count = lib.xkb_keymap_key_get_mods_for_level(keymap, code, layout, level, masks, 64)
                    choices = [mask for mask in masks[:min(count, 64)] if not mask & ~allowed]
                    if not choices:
                        continue
                    mask = min(choices, key=int.bit_count)
                    symbols = C.POINTER(u32)()
                    count = lib.xkb_keymap_key_get_syms_by_level(keymap, code, layout, level, C.byref(symbols))
                    # A key producing several symbols cannot represent one text
                    # character exactly; don't silently include it in the map.
                    if count != 1:
                        continue
                    symbol = symbols[0]
                    entry = (code - 8, mask)
                    self._insert(self.symbols, symbol, entry)
                    character = lib.xkb_keysym_to_utf32(symbol)
                    if character:
                        self._insert(self.characters, chr(character), entry)
        finally:
            if keymap:
                lib.xkb_keymap_unref(keymap)
            lib.xkb_context_unref(context)

    @staticmethod
    def _insert(mapping, key, entry):
        if key not in mapping or entry[1].bit_count() < mapping[key][1].bit_count():
            mapping[key] = entry

    def symbol(self, symbol):
        return self.symbols.get(symbol)

    def character(self, character):
        return self.characters.get(character)

    def modifiers(self, mask):
        codes = []
        for bit, symbol in self.modifier_symbols.items():
            if mask & bit:
                entry = self.symbol(symbol)
                if entry is None or entry[1]:
                    raise RuntimeError('Compositor keymap has no usable modifier key')
                codes.append(entry[0])
        return codes
