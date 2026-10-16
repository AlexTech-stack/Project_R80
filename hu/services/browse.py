"""The browse tree of hu-mediad: one source's tracks by folder, artist and album.

A path names a list; its entries are lists to open or tracks to play:

    ""                              the menu: Folders, Artists, Albums, All tracks
    "folders" / "folders/<dir>"     sub-folders, then the folder's tracks by file name
    "artists"                       artists A-Z ("Unknown artist" for tracks without one)
    "artists/<artist>"              that artist's albums
    "artists/<artist>/<album>"      that artist's tracks of the album
    "albums" / "albums/<album>"     albums A-Z / an album's tracks by track number
    "tracks"                        every track, in path order (the default queue)

Path segments are percent-encoded (urllib.parse.quote); an album is its name plus its
folder, so two albums of the same name in different folders stay apart. Entries are
dicts: kind (menu|folder|artist|album|track), id (the path to open, for lists),
title, subtitle, count (tracks below), cover, and for tracks duration and index (the
position among the tracks of this list, what PlayFrom takes) plus "track", the
track itself. Standard library only.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote, unquote

UNKNOWN_ARTIST = "Unknown artist"


def _q(s: str) -> str:
    return quote(s, safe="")


def _artist(t: dict) -> str:
    return t["artist"] or UNKNOWN_ARTIST


def _folder(t: dict, root: Path) -> str:
    try:
        rel = str(Path(t["path"]).parent.relative_to(root))
    except ValueError:
        return ""
    return "" if rel == "." else rel


def _album_key(t: dict, root: Path) -> str:
    return _q(t["album"] + "\x00" + _folder(t, root))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _by_track_number(tracks: list) -> list:
    return sorted(tracks, key=lambda t: (t["trackNumber"] or 9999, Path(t["path"]).name.lower()))


def _albums(tracks: list, root: Path) -> "OrderedDict[str, list]":
    groups: dict[str, list] = {}
    for t in tracks:
        groups.setdefault(_album_key(t, root), []).append(t)
    keys = sorted(groups, key=lambda k: (groups[k][0]["album"].lower(), k))
    return OrderedDict((k, _by_track_number(groups[k])) for k in keys)


def _cover(tracks: list) -> str:
    return next((t["cover"] for t in tracks if t["cover"]), "")


def _list_entry(kind: str, path: str, title: str, tracks: list, subtitle: str = "") -> dict:
    return {"kind": kind, "id": path, "title": title, "subtitle": subtitle or _plural(len(tracks), "track"),
            "count": len(tracks), "cover": _cover(tracks), "duration": 0, "index": -1}


def _track_entries(tracks: list) -> list:
    return [{"kind": "track", "id": "", "title": t["title"], "subtitle": t["artist"], "count": 0,
             "cover": t["cover"], "duration": t["duration"], "index": i, "track": t}
            for i, t in enumerate(tracks)]


def browse(tracks: list, root: Path, source: str, path: str) -> tuple[str, list]:
    """(title, entries) of the list at path; KeyError if there is none."""
    parts = [unquote(p) for p in path.split("/")] if path else []
    head = parts[0] if parts else ""
    if not parts:
        albums = _albums(tracks, root)
        artists = {_artist(t) for t in tracks}
        return source, [
            _list_entry("menu", "folders", "Folders", tracks),
            {**_list_entry("menu", "artists", "Artists", tracks), "subtitle": _plural(len(artists), "artist")},
            {**_list_entry("menu", "albums", "Albums", tracks), "subtitle": _plural(len(albums), "album")},
            _list_entry("menu", "tracks", "All tracks", tracks),
        ]
    if head == "tracks" and len(parts) == 1:
        return "All tracks", _track_entries(tracks)
    if head == "folders":
        rel = "/".join(parts[1:])
        inside = [t for t in tracks if _folder(t, root) == rel or _folder(t, root).startswith(rel + "/") or not rel]
        if rel and not inside:
            raise KeyError(path)
        subs: dict[str, list] = {}
        here = []
        for t in inside:
            f = _folder(t, root)
            if f == rel:
                here.append(t)
            else:
                name = (f[len(rel) + 1:] if rel else f).split("/")[0]
                subs.setdefault(name, []).append(t)
        entries = [_list_entry("folder", "folders/" + "/".join(_q(p) for p in (rel.split("/") if rel else []) + [n]), n, subs[n])
                   for n in sorted(subs, key=str.lower)]
        here.sort(key=lambda t: Path(t["path"]).name.lower())
        return (rel.rsplit("/", 1)[-1] if rel else source), entries + _track_entries(here)
    if head == "albums":
        albums = _albums(tracks, root)
        if len(parts) == 1:
            entries = []
            for k, ts in albums.items():
                artists = {_artist(t) for t in ts}
                entries.append(_list_entry("album", f"albums/{k}", ts[0]["album"] or "Unknown album", ts,
                                           artists.pop() if len(artists) == 1 else "Various artists"))
            return "Albums", entries
        k = _q(parts[1])
        if len(parts) != 2 or k not in albums:
            raise KeyError(path)
        return albums[k][0]["album"] or "Unknown album", _track_entries(albums[k])
    if head == "artists":
        if len(parts) == 1:
            groups: dict[str, list] = {}
            for t in tracks:
                groups.setdefault(_artist(t), []).append(t)
            return "Artists", [_list_entry("artist", f"artists/{_q(a)}", a, groups[a],
                                           _plural(len(_albums(groups[a], root)), "album"))
                               for a in sorted(groups, key=str.lower)]
        artist = parts[1]
        mine = [t for t in tracks if _artist(t) == artist]
        if not mine:
            raise KeyError(path)
        albums = _albums(mine, root)
        if len(parts) == 2:
            return artist, [_list_entry("album", f"artists/{_q(artist)}/{k}", ts[0]["album"] or "Unknown album", ts)
                            for k, ts in albums.items()]
        k = _q(parts[2])
        if len(parts) != 3 or k not in albums:
            raise KeyError(path)
        return albums[k][0]["album"] or "Unknown album", _track_entries(albums[k])
    raise KeyError(path)


def tracks_of(tracks: list, root: Path, source: str, path: str) -> tuple[str, list]:
    """(title, the tracks of the list at path, in its order): what PlayFrom queues."""
    title, entries = browse(tracks, root, source, path)
    return title, [e["track"] for e in entries if e["kind"] == "track"]
