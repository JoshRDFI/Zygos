"""Fake keyring backends shared by the secret store tests."""

import time


class FakeKeyring:
    priority = 1  # a real keychain (keyring backends below 1 are not)

    def __init__(self):
        self.entries = {}

    def get_password(self, service, username):
        return self.entries.get((service, username))

    def set_password(self, service, username, password):
        self.entries[(service, username)] = password

    def delete_password(self, service, username):
        from keyring.errors import PasswordDeleteError

        if (service, username) not in self.entries:
            raise PasswordDeleteError("not found")
        del self.entries[(service, username)]


class RaisingKeyring(FakeKeyring):
    def get_password(self, service, username):
        raise RuntimeError("locked SENTINEL-77")


class SlowKeyring(FakeKeyring):
    def get_password(self, service, username):
        time.sleep(1)
        return None


def backend_in(module):
    """An object whose class lives in ``module`` (e.g. ``keyring.backends.fail``)."""
    return type("Keyring", (), {"__module__": module})()
