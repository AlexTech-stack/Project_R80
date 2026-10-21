"""The services' log: DLT (AUTOSAR Diagnostic Log and Trace, protocol version 1).

Each service is one DLT application (a short ID such as "MED"), each part of it a
context ("MAIN", "USB", ...). The lines go to the COVESA dlt-daemon through its
library libdlt (ctypes, no extra Python package); the daemon keeps them in its files
and serves DLT Viewer (TCP 3490). The services use plain Python logging:

    log = dlt.context("USB", "USB sticks")      # at import: a logging.Logger
    ...
    dlt.app("MED", "Media service", "mediad")   # in main(), before the first line
    log.info("removable medium %s", key)

A log level set from outside (DLT Viewer, Settings -> System) reaches the logger, so a
line below it is not even formatted. Every line also goes to stderr ("[mediad] ...",
info and up; R80_LOG_STDERR=debug|warning|...), which is all there is without libdlt
(demo, cloud sessions) or with R80_DLT=0. The daemon's pipe directory and port follow
DLT_PIPE_DIR and DLT_DAEMON_TCP_PORT, as libdlt reads them.

Never log personal data: phone numbers, contacts, names, streets (D13).
"""
from __future__ import annotations

import atexit
import ctypes
import ctypes.util
import logging
import os
import sys

VERBOSE = 5                                         # DLT_LOG_VERBOSE, below logging.DEBUG
logging.addLevelName(VERBOSE, "VERBOSE")
MAX_TEXT = 1000                                     # bytes; libdlt's message buffer is 1390

# DLT log levels (PRS_Dlt: 0 off, 1 fatal ... 6 verbose) <-> logging levels
TO_DLT = ((logging.CRITICAL, 1), (logging.ERROR, 2), (logging.WARNING, 3), (logging.INFO, 4),
          (logging.DEBUG, 5), (VERBOSE, 6))
FROM_DLT = {0: logging.CRITICAL + 10, 1: logging.CRITICAL, 2: logging.ERROR, 3: logging.WARNING,
            4: logging.INFO, 5: logging.DEBUG, 6: VERBOSE}
NAMES = {"off": 0, "fatal": 1, "error": 2, "warning": 3, "info": 4, "debug": 5, "verbose": 6}

_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_char), ctypes.c_uint8, ctypes.c_uint8)
_lib = None
_app = None
_contexts: dict[str, tuple[logging.Logger, str]] = {}   # id -> (logger, description)
_handles: dict[str, ctypes.Array] = {}                   # id -> DltContext (opaque)
_stderr = logging.StreamHandler(sys.stderr)


def address(mac: str) -> str:
    """A Bluetooth address as the log shows it: only its last two bytes (..:EE:FF)."""
    return "..:" + mac[-5:] if len(mac) > 5 else mac


def dlt_level(levelno: int) -> int:
    for py, d in TO_DLT:
        if levelno >= py:
            return d
    return 6


def _load():
    if os.environ.get("R80_DLT", "1") == "0":
        return None
    for name in (ctypes.util.find_library("dlt"), "libdlt.so.3", "libdlt.so.2"):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        lib.dlt_register_app.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.dlt_register_context.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.dlt_log_string.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
        lib.dlt_register_log_level_changed_callback.argtypes = [ctypes.c_void_p, _CALLBACK]
        return lib
    return None


@_CALLBACK
def _level_changed(context_id, level, _trace_status):
    """libdlt's thread: the daemon set a context's level (DLT Viewer, Settings -> System)."""
    cid = ctypes.string_at(context_id, 4).rstrip(b"\0").decode("ascii", "replace")
    if cid in _contexts:
        _contexts[cid][0].setLevel(FROM_DLT.get(level, logging.INFO))


class DltHandler(logging.Handler):
    def __init__(self, cid: str):
        super().__init__()
        self.cid = cid

    def emit(self, record):
        handle = _handles.get(self.cid)
        if handle is None:
            return
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + logging.Formatter().formatException(record.exc_info)
        except Exception:                           # a bad format string must not stop the service
            self.handleError(record)
            return
        for line in text.splitlines() or [""]:
            data = line.encode("utf-8", "replace")
            if len(data) > MAX_TEXT:
                data = data[:MAX_TEXT - 3] + b"..."
            _lib.dlt_log_string(handle, dlt_level(record.levelno), data)


def _register(cid: str):
    logger, description = _contexts[cid]
    handle = ctypes.create_string_buffer(256)        # DltContext, opaque (its layout differs per libdlt version)
    if _lib.dlt_register_context(handle, cid.encode(), description.encode()) != 0:
        return
    _handles[cid] = handle
    _lib.dlt_register_log_level_changed_callback(handle, _level_changed)
    logger.addHandler(DltHandler(cid))


def context(cid: str, description: str = "") -> logging.Logger:
    """The logger of one context (up to 4 characters). Registered with DLT once app() ran."""
    cid = cid[:4]
    if cid in _contexts:
        return _contexts[cid][0]
    logger = logging.getLogger("r80." + cid)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(_stderr)
    _contexts[cid] = (logger, description or cid)
    if _app is not None and _lib is not None:
        _register(cid)
    return logger


def app(apid: str, description: str, tag: str) -> bool:
    """This process is DLT application `apid`; stderr lines start with [tag]. True if libdlt is there."""
    global _lib, _app
    _stderr.setFormatter(logging.Formatter(f"[{tag}] %(message)s"))
    _stderr.setLevel(NAMES_TO_LOGGING.get(os.environ.get("R80_LOG_STDERR", "info"), logging.INFO))
    _app = apid[:4]
    _lib = _load()
    if _lib is None or _lib.dlt_register_app(_app.encode(), description.encode()) != 0:
        _lib = None
        return False
    atexit.register(_lib.dlt_unregister_app_flush_buffered_logs)
    for cid in list(_contexts):
        _register(cid)
    return True


NAMES_TO_LOGGING = {name: FROM_DLT[n] for name, n in NAMES.items()}
