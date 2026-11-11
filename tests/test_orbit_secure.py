import tempfile
import unittest
from pathlib import Path

from orbit_secure import AESGCM, KeystoreError, PROFILE_VAULT, ProfileRestoreError, Vault


class MemoryKeystore:
    name = "Test keystore"

    def __init__(self, key=None):
        self.key = key

    def load(self):
        if self.key is False:
            raise KeystoreError("Locked")
        return self.key

    def store(self, key):
        self.key = key


@unittest.skipUnless(AESGCM is not None, "Requires cryptography")
class ProfileVaultTest(unittest.TestCase):
    def test_locked_keyring_preserves_saved_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            profile = directory / "browser"
            profile.mkdir()
            (profile / "test-data").write_bytes(b"local fixture")
            keystore = MemoryKeystore()
            vault = Vault(directory, keystore)
            self.assertTrue(vault.seal_profile(profile))
            sealed = directory / PROFILE_VAULT
            encrypted = sealed.read_bytes()

            with self.assertRaises(ProfileRestoreError):
                Vault(directory, MemoryKeystore(False)).open_profile(profile)
            self.assertFalse(profile.exists())
            self.assertEqual(sealed.read_bytes(), encrypted)

            vault.open_profile(profile)
            self.assertEqual((profile / "test-data").read_bytes(), b"local fixture")
