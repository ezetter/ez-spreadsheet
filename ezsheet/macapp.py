"""EZ Sheet's name for macOS, as the menu bar and the Dock show it: the app's
bundle name, set before the QApplication is made. (Run as python -m
ezsheet, the process is Python's, so it would otherwise say python3.)

This talks to the Objective-C runtime through ctypes, as PySide doesn't wrap
AppKit; off a Mac it does nothing.
"""

import ctypes
import ctypes.util
import sys

APP_NAME = "EZ Sheet"


def set_app_name(name: str = APP_NAME) -> bool:
    """Name the app `name` in its bundle's information, as AppKit reads it;
    whether it could."""
    if sys.platform != "darwin":
        return False
    path = ctypes.util.find_library("objc")
    if not path:
        return False
    objc = ctypes.cdll.LoadLibrary(path)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))  # (NSBundle and NSString)

    def send(obj, selector, *args, restype=ctypes.c_void_p, argtypes=()):
        function = ctypes.cast(objc.objc_msgSend,
                               ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
        return function(obj, objc.sel_registerName(selector.encode()), *args)

    def string(text):
        return send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", text.encode(),
                    argtypes=[ctypes.c_char_p])

    bundle = send(objc.objc_getClass(b"NSBundle"), "mainBundle")
    info = send(bundle, "infoDictionary") if bundle else None
    if not info:
        return False
    for key in ("CFBundleName", "CFBundleDisplayName"):  # (it's mutable, though it's given as a dictionary)
        send(info, "setObject:forKey:", string(name), string(key), restype=None,
             argtypes=[ctypes.c_void_p, ctypes.c_void_p])
    return True
