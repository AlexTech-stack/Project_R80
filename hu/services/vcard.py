"""vCards as phones send them over PBAP (vCard 2.1 and 3.0): contacts and call history.

    contacts(text)  -> [{"id", "name", "numbers": [{"number", "type"}]}], sorted by name
    history(text)   -> [{"name", "number", "kind": in|out|missed, "time": "YYYY-MM-DD HH:MM"}]

Handles folded lines, QUOTED-PRINTABLE with soft line breaks (vCard 2.1, CHARSET=UTF-8),
TYPE=... and bare parameters (2.1: TEL;CELL:...), and the call-history stamp
X-IRMC-CALL-DATETIME;RECEIVED|DIALED|MISSED (or TYPE=...). A contact's id is a hash of
its name and numbers, so local favourites survive a re-sync. Standard library only.
"""
from __future__ import annotations

import hashlib
import quopri
import re

TYPES = {"CELL": "mobile", "MOBILE": "mobile", "HOME": "home", "WORK": "work", "MAIN": "main", "FAX": "fax"}
KINDS = {"RECEIVED": "in", "DIALED": "out", "MISSED": "missed"}


def _lines(text: str) -> list[str]:
    """Logical lines: folding undone (3.0: a leading space; 2.1 QP: a trailing '=')."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if out and raw[:1] in (" ", "\t"):
            out[-1] += raw[1:]
        elif out and out[-1].endswith("=") and "QUOTED-PRINTABLE" in out[-1].split(":", 1)[0].upper():
            out[-1] = out[-1][:-1] + raw
        else:
            out.append(raw)
    return [line for line in out if line.strip()]


def _parse(line: str):
    """(NAME, [params upper-case], value) of one content line."""
    head, _, value = line.partition(":")
    parts = head.split(";")
    name = parts[0].split(".")[-1].upper()          # item1.TEL -> TEL
    params: list[str] = []
    charset = "utf-8"
    for p in parts[1:]:
        k, eq, v = p.partition("=")
        if eq and k.upper() == "CHARSET":
            charset = v
        elif eq and k.upper() == "TYPE":
            params += [x.upper() for x in v.split(",")]
        elif eq and k.upper() == "ENCODING":
            params.append(v.upper())
        else:
            params.append(p.upper())
    if "QUOTED-PRINTABLE" in params:
        value = quopri.decodestring(value.encode("latin-1", "replace")).decode(charset, "replace")
    return name, params, value


def _unescape(v: str) -> str:
    return v.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ").replace("\\\\", "\\").strip()


def _cards(text: str):
    card = None
    for line in _lines(text):
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            card = []
        elif upper.startswith("END:VCARD"):
            if card is not None:
                yield card
            card = None
        elif card is not None:
            card.append(_parse(line))


def _name(card) -> str:
    fn = next((_unescape(v) for n, _, v in card if n == "FN" and v.strip()), "")
    if fn:
        return fn
    n = next((v for n, _, v in card if n == "N"), "")
    parts = [_unescape(x) for x in n.split(";")]
    return " ".join(x for x in (parts[1:2] + parts[:1]) if x).strip()      # given family


def _number(v: str) -> str:
    v = v.strip()
    if v.lower().startswith("tel:"):
        v = v[4:]
    return re.sub(r"[^0-9+*#]", "", v)


def _numbers(card) -> list[dict]:
    out, seen = [], set()
    for n, params, v in card:
        if n != "TEL":
            continue
        number = _number(v)
        if not number or number in seen:
            continue
        seen.add(number)
        kind = next((TYPES[p] for p in params if p in TYPES), "other")
        out.append({"number": number, "type": kind})
    return out


def contact_id(name: str, numbers: list[dict]) -> str:
    key = name + "\x00" + "\x00".join(sorted(n["number"] for n in numbers))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def contacts(text: str, skip_owner: bool = True) -> list[dict]:
    """The phonebook (PBAP "pb"); its first card is the phone's owner and is left out."""
    out = []
    for i, card in enumerate(_cards(text)):
        if i == 0 and skip_owner:
            continue
        name, numbers = _name(card), _numbers(card)
        if not numbers:
            continue
        name = name or numbers[0]["number"]
        out.append({"id": contact_id(name, numbers), "name": name, "numbers": numbers})
    out.sort(key=lambda c: c["name"].casefold())
    return out


def _time(stamp: str) -> str:
    m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})", stamp.strip())
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else ""


def history(text: str) -> list[dict]:
    """The combined call history (PBAP "cch"), newest first as the phone sends it."""
    out = []
    for card in _cards(text):
        stamp = next(((params, v) for n, params, v in card if n == "X-IRMC-CALL-DATETIME"), None)
        if stamp is None:
            continue
        params, value = stamp
        kind = next((KINDS[p] for p in params if p in KINDS), "in")
        numbers = _numbers(card)
        out.append({"name": _name(card), "number": numbers[0]["number"] if numbers else "", "kind": kind,
                    "time": _time(value)})
    return out


def same_number(a: str, b: str) -> bool:
    """The same line, written with or without the country code (+49 171... = 0171...)."""
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    return bool(da and db) and (da == db or (min(len(da), len(db)) >= 7 and da[-9:] == db[-9:]))
