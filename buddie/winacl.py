"""Whether a file on Windows is out of this user's control, read from its security descriptors (standard library
ctypes, advapi32; no dependency). Used by policy.protection_problem.

For the file and for every directory above its real path:
  owner   must be SYSTEM, Administrators or TrustedInstaller: an owner may always rewrite the DACL, so a file owned
          by this user (or by any one account) is this user's to control
  DACL    must exist, and no ACE that applies to the object may grant a low-privilege principal (Everyone,
          Authenticated Users, Users, INTERACTIVE, Guests, OWNER RIGHTS, or this user) a right that controls it: on
          the file writing, appending, writing attributes, deleting, changing its DACL or owner; on a directory
          deleting it or a child, or changing its DACL or owner. Deny ACEs are not subtracted: an ACE that would be
          overridden still counts, so the check can only err towards "not protected". An allow ACE of any other
          type that applies (object, callback/conditional, compound) is not read, so it is a problem too
  access  when the process is not elevated, AccessCheck with this process's own token must grant none of those
          rights either: that covers groups this user is in that the list above does not name. An elevated process
          (an administrator's) is outside the threat model, as root is on POSIX: its token can do anything, so only
          the owner and the DACL are judged then
Anything that cannot be read or decided is a problem: protection is established or it is not claimed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

TRUSTED_OWNERS = {"S-1-5-18": "SYSTEM", "S-1-5-32-544": "Administrators",
                  "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464": "TrustedInstaller"}
LOW = {"S-1-1-0": "Everyone", "S-1-5-11": "Authenticated Users", "S-1-5-32-545": "Users", "S-1-5-4": "INTERACTIVE",
       "S-1-5-32-546": "Guests", "S-1-3-4": "OWNER RIGHTS", "S-1-2-0": "LOCAL", "S-1-2-1": "CONSOLE LOGON"}
DELETE, WRITE_DAC, WRITE_OWNER = 0x10000, 0x40000, 0x80000
GENERIC_ALL, GENERIC_WRITE = 0x10000000, 0x40000000
FILE_CONTROL = 0x2 | 0x4 | 0x10 | 0x100 | DELETE | WRITE_DAC | WRITE_OWNER | GENERIC_ALL | GENERIC_WRITE
DIR_CONTROL = 0x40 | DELETE | WRITE_DAC | WRITE_OWNER | GENERIC_ALL | GENERIC_WRITE  # 0x40: FILE_DELETE_CHILD
INHERIT_ONLY = 0x08
ACCESS_ALLOWED = 0
DENIED = {1, 6, 10, 12}  # ACCESS_DENIED, _OBJECT, _CALLBACK, _CALLBACK_OBJECT: never subtracted, so never a problem


@dataclass(frozen=True)
class Node:
    path: str
    is_dir: bool
    owner: str | None                       # SID string, None when it could not be read
    aces: tuple[tuple[int, int, int, str], ...] | None  # (type, flags, mask, sid); None: no DACL (everyone, all)
    granted: int | None = None              # AccessCheck's MAXIMUM_ALLOWED for this token; None: not judged


def judge(nodes: list[Node], user_sid: str) -> str | None:
    """The first reason the file (nodes[0]) and its directories are not out of the user's control, or None."""
    low = {**LOW, user_sid: "this user"}
    for n in nodes:
        control = DIR_CONTROL if n.is_dir else FILE_CONTROL
        if n.owner is None:
            return f"{n.path}: its owner cannot be read"
        if n.owner not in TRUSTED_OWNERS:
            return f"{n.path} is owned by {low.get(n.owner, n.owner)}, not by SYSTEM, Administrators or TrustedInstaller"
        if n.aces is None:
            return f"{n.path} has no DACL: everyone may do anything with it"
        for kind, flags, mask, sid in n.aces:
            if flags & INHERIT_ONLY or kind in DENIED:
                continue
            if kind != ACCESS_ALLOWED:
                return f"{n.path} has an allow ACE of type {kind} that this check does not read"
            if sid in low and mask & control:
                return f"{n.path}: {low[sid]} may change or replace it (ACE mask {mask:#x})"
        if n.granted is not None and n.granted & control:
            return f"{n.path}: this user's token is granted {n.granted & control:#x} on it"
    return None


def problem(path: str) -> str | None:
    """Why the file at `path` is within this user's control, or None when it is not (Windows only)."""
    try:
        real = os.path.realpath(path)
        nodes, here = [], real
        while True:
            nodes.append(_node(here, is_dir=here != real))
            parent = os.path.dirname(here)
            if parent == here:
                break
            here = parent
        return judge(nodes, _user_sid())
    except OSError as error:
        return f"cannot establish protection: {error}"


# --- ctypes ---------------------------------------------------------------------------------------------------------

def _api():
    import ctypes
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.POINTER(ctypes.c_void_p)]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    adv.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.DuplicateToken.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    adv.AccessCheck.argtypes = [ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                ctypes.POINTER(wintypes.BOOL)]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, adv, k32


def _fail(what: str):
    import ctypes
    raise OSError(f"{what} failed (Windows error {ctypes.get_last_error()})")


def _sid_string(sid) -> str:
    ctypes, wintypes, adv, k32 = _api()
    out = wintypes.LPWSTR()
    if not adv.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        _fail("ConvertSidToStringSidW")
    try:
        return out.value
    finally:
        k32.LocalFree(out)


def _token():
    ctypes, wintypes, adv, k32 = _api()
    tok = wintypes.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008 | 0x0002, ctypes.byref(tok)):  # QUERY, DUPLICATE
        _fail("OpenProcessToken")
    return tok


def _user_sid() -> str:
    ctypes, wintypes, adv, k32 = _api()
    tok = _token()
    try:
        size = wintypes.DWORD()
        adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(size))  # TokenUser
        buf = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(tok, 1, buf, size, ctypes.byref(size)):
            _fail("GetTokenInformation(TokenUser)")
        return _sid_string(ctypes.c_void_p.from_buffer(buf).value)
    finally:
        k32.CloseHandle(tok)


def elevated() -> bool:
    ctypes, wintypes, adv, k32 = _api()
    tok = _token()
    try:
        val, size = wintypes.DWORD(), wintypes.DWORD()
        if not adv.GetTokenInformation(tok, 20, ctypes.byref(val), 4, ctypes.byref(size)):  # TokenElevation
            _fail("GetTokenInformation(TokenElevation)")
        return bool(val.value)
    finally:
        k32.CloseHandle(tok)


def _node(path: str, is_dir: bool) -> Node:
    ctypes, wintypes, adv, k32 = _api()
    owner, group, dacl, sd = (ctypes.c_void_p() for _ in range(4))
    # SE_FILE_OBJECT = 1; OWNER | GROUP | DACL
    err = adv.GetNamedSecurityInfoW(path, 1, 0x1 | 0x2 | 0x4, ctypes.byref(owner), ctypes.byref(group),
                                    ctypes.byref(dacl), None, ctypes.byref(sd))
    if err:
        raise OSError(f"GetNamedSecurityInfoW({path}) failed (Windows error {err})")
    try:
        owner_sid = _sid_string(owner) if owner.value else None
        aces = None
        if dacl.value:
            class Info(ctypes.Structure):
                _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]

            class Header(ctypes.Structure):
                _fields_ = [("type", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("size", ctypes.c_ushort),
                            ("mask", wintypes.DWORD)]
            info = Info()
            if not adv.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):  # AclSizeInformation
                _fail("GetAclInformation")
            out = []
            for i in range(info.count):
                ace = ctypes.c_void_p()
                if not adv.GetAce(dacl, i, ctypes.byref(ace)):
                    _fail("GetAce")
                h = Header.from_address(ace.value)
                # ACCESS_ALLOWED / ACCESS_DENIED ACEs: header, mask, then the SID; other types carry no plain SID
                sid = _sid_string(ace.value + 8) if h.type in (0, 1) else ""
                out.append((h.type, h.flags, h.mask, sid))
            aces = tuple(out)
        granted = None if elevated() else _granted(sd)
        return Node(path, is_dir, owner_sid, aces, granted)
    finally:
        k32.LocalFree(sd)


def _granted(sd) -> int:
    """AccessCheck(MAXIMUM_ALLOWED) for this process's token on the security descriptor `sd`."""
    ctypes, wintypes, adv, k32 = _api()

    class Mapping(ctypes.Structure):
        _fields_ = [("read", wintypes.DWORD), ("write", wintypes.DWORD), ("execute", wintypes.DWORD),
                    ("all", wintypes.DWORD)]
    tok, imp = _token(), wintypes.HANDLE()
    try:
        if not adv.DuplicateToken(tok, 2, ctypes.byref(imp)):  # SecurityImpersonation
            _fail("DuplicateToken")
        mapping = Mapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)  # FILE_GENERIC_*, FILE_ALL_ACCESS
        privs, privs_len = ctypes.create_string_buffer(256), wintypes.DWORD(256)
        granted, status = wintypes.DWORD(), wintypes.BOOL()
        if not adv.AccessCheck(sd, imp, 0x02000000, ctypes.byref(mapping), privs, ctypes.byref(privs_len),
                               ctypes.byref(granted), ctypes.byref(status)):
            _fail("AccessCheck")
        return granted.value if status.value else 0
    finally:
        k32.CloseHandle(tok)
        if imp.value:
            k32.CloseHandle(imp)
