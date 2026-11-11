"""At-rest protection for Orbit Tabs data.

A random 256-bit key lives in the operating system's keystore (Windows DPAPI, the macOS Keychain, or the
Secret Service on Linux). It never touches the disk in readable form. With that key:

* the browser profile (sign-in cookies, local storage) is sealed into an AES-256-GCM vault when the app
  exits and unpacked when it starts, and
* cached course covers are stored as individual AES-256-GCM blobs.

Without a usable keystore nothing is written encrypted with a guessable key: covers stay in memory and
the profile is left as the browser engine wrote it, and the status says so.
"""
from __future__ import annotations

import hashlib
import io
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # The app still runs; protection reports itself as unavailable.
    AESGCM = None
    InvalidTag = ValueError

MAGIC = b"OTV1"
SERVICE = "Orbit Tabs"
ACCOUNT = "vault-key"
PROFILE_VAULT = "browser.vault"
MAX_PROFILE_BYTES = 512 * 1024 * 1024
# Regenerable engine caches are left out of the vault to keep sealing quick.
SKIPPED_PARTS = {"GPUCache", "Code Cache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "GrShaderCache",
                 "ShaderCache", "CacheStorage", "ScriptCache", "Crashpad"}


class KeystoreError(RuntimeError):
    pass


class ProfileRestoreError(RuntimeError):
    pass


# ---------------------------------------------------------------- keystore backends

def _windows_dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(value):
        buffer = ctypes.create_string_buffer(value, len(value))
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, _source_buffer = blob(data)
    entropy, _entropy_buffer = blob(b"Orbit Tabs vault key")
    output = Blob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(source), "Orbit Tabs", ctypes.byref(entropy), None, None, flags,
                                      ctypes.byref(output))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None, flags,
                                        ctypes.byref(output))
    if not ok:
        raise KeystoreError(f"Windows data protection failed ({ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _run(command, *, data=None):
    try:
        return subprocess.run(command, input=data, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise KeystoreError(str(error)) from error


class Keystore:
    """Load or create the vault key. Returns None when no key exists yet; raises when the store fails."""

    def __init__(self, directory: Path):
        self.directory = directory
        if sys.platform == "win32":
            self.name = "Windows Data Protection (DPAPI)"
        elif sys.platform == "darwin":
            self.name = "macOS Keychain"
        else:
            self.name = "Secret Service keyring"

    def load(self) -> bytes | None:
        if sys.platform == "win32":
            path = self.directory / "vault-key.dpapi"
            return bytes.fromhex(_windows_dpapi(path.read_bytes(), False).decode()) if path.exists() else None
        if sys.platform == "darwin":
            result = _run(["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"])
            if result.returncode == 44:
                return None
            if result.returncode:
                raise KeystoreError(result.stderr.decode(errors="replace").strip() or "Keychain lookup failed.")
            return bytes.fromhex(result.stdout.decode().strip())
        if not shutil.which("secret-tool"):
            raise KeystoreError("secret-tool is not installed.")
        result = _run(["secret-tool", "lookup", "service", "orbit-tabs", "account", ACCOUNT])
        if result.returncode == 0 and result.stdout.strip():
            return bytes.fromhex(result.stdout.decode().strip())
        if result.stderr.strip():
            raise KeystoreError(result.stderr.decode(errors="replace").strip())
        return None

    def store(self, key: bytes) -> None:
        secret = key.hex().encode()
        if sys.platform == "win32":
            path = self.directory / "vault-key.dpapi"
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(_windows_dpapi(secret, True))
            temporary.replace(path)
            return
        if sys.platform == "darwin":
            result = _run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", secret.decode()])
        else:
            result = _run(["secret-tool", "store", "--label=Orbit Tabs vault key", "service", "orbit-tabs",
                           "account", ACCOUNT], data=secret)
        if result.returncode:
            raise KeystoreError(result.stderr.decode(errors="replace").strip() or "Could not save the key.")


# ---------------------------------------------------------------- vault

class Vault:
    def __init__(self, directory: Path, keystore: Keystore | None = None):
        self.directory = directory
        self.keystore = keystore or Keystore(directory)
        self.key = None
        self.status = ""
        self.profile_status = ""
        self.marker = directory / "vault-key.id"
        if AESGCM is None:
            self.status = "Encryption library missing; nothing is encrypted."
            return
        try:
            key = self.keystore.load()
            if key is None:
                if self.marker.exists():
                    # A key was made before but the store no longer has it. Never silently replace it.
                    raise KeystoreError("the saved key is missing from the keystore")
                key = secrets.token_bytes(32)
                self.keystore.store(key)
                self.marker.write_text(self.fingerprint(key) + "\n", encoding="ascii")
            if len(key) != 32:
                raise KeystoreError("the saved key has the wrong length")
            if not self.marker.exists():
                self.marker.write_text(self.fingerprint(key) + "\n", encoding="ascii")
            if self.marker.exists() and self.marker.read_text(encoding="ascii").strip() != self.fingerprint(key):
                raise KeystoreError("the keystore returned a different key")
            self.key = key
            self.status = f"AES-256-GCM, key held by {self.keystore.name}."
        except (KeystoreError, OSError, ValueError) as error:
            self.status = f"{self.keystore.name} unavailable ({error}); covers stay in memory and the profile is not sealed."

    @staticmethod
    def fingerprint(key: bytes) -> str:
        return hashlib.sha256(b"orbit-tabs-key-id" + key).hexdigest()[:16]

    @property
    def available(self) -> bool:
        return self.key is not None

    def encrypt(self, data: bytes, purpose: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return MAGIC + nonce + AESGCM(self.key).encrypt(nonce, data, purpose)

    def decrypt(self, blob: bytes, purpose: bytes) -> bytes:
        if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 12 + 16:
            raise ValueError("Not an Orbit Tabs vault blob.")
        nonce = blob[len(MAGIC):len(MAGIC) + 12]
        return AESGCM(self.key).decrypt(nonce, blob[len(MAGIC) + 12:], purpose)

    def write(self, path: Path, data: bytes, purpose: bytes) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(self.encrypt(data, purpose))
        temporary.replace(path)

    # -------------------------------------------------------- browser profile

    def open_profile(self, profile: Path) -> None:
        """Unpack the sealed profile before the browser engine starts."""
        vault = profile.with_name(PROFILE_VAULT)
        if profile.exists() and any(profile.iterdir()):
            # Left over from a crash, or the first run after upgrading: it is the newest copy.
            self.profile_status = ("Profile found unsealed; it will be sealed when Orbit Tabs quits."
                                   if self.available else "Profile is not sealed.")
            return
        if not vault.exists():
            self.profile_status = "No saved sign-in yet." if self.available else "Profile is not sealed."
            return
        if not self.available:
            raise ProfileRestoreError("Your saved sign-in is encrypted. Unlock the system keyring and reopen Orbit Tabs.")
        try:
            data = self.decrypt(vault.read_bytes(), b"profile")
            with tempfile.TemporaryDirectory(prefix="profile-restore-", dir=profile.parent) as temporary:
                restored = Path(temporary) / "browser"
                restored.mkdir()
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    archive.extractall(restored)
                if profile.exists():
                    profile.rmdir()
                restored.replace(profile)
        except (InvalidTag, ValueError, OSError, zipfile.BadZipFile) as error:
            raise ProfileRestoreError("The encrypted browser profile could not be restored. "
                                      "Your saved archive is still in the app data folder.") from error
        self.profile_status = "Sign-in restored from the encrypted vault."

    def seal_profile(self, profile: Path) -> bool:
        """Encrypt the profile into the vault and remove the readable copy. Call after the engine has shut down."""
        if not self.available or not profile.exists():
            return False
        buffer = io.BytesIO()
        total = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            for path in sorted(profile.rglob("*")):
                relative = path.relative_to(profile)
                if not path.is_file() or path.is_symlink() or SKIPPED_PARTS.intersection(relative.parts):
                    continue
                total += path.stat().st_size
                if total > MAX_PROFILE_BYTES:
                    self.profile_status = "Profile is too large to seal; it was left in place."
                    return False
                archive.write(path, relative.as_posix())
        if not total:
            return False
        self.write(profile.with_name(PROFILE_VAULT), buffer.getvalue(), b"profile")
        with tempfile.TemporaryDirectory(prefix="profile-cleanup-", dir=profile.parent) as temporary:
            profile.replace(Path(temporary) / "browser")
        return True


def prepare_data_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(directory, 0o700)
