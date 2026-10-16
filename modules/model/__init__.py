"""V4 model management — Provider / Model / Scene / Credential (pure logic).

Ownership: `modules/model`.  Pure data + validation + JSON files (atomic 600 writes);
NO gateway/audio imports, no network.  Mirrors the conventions of
`modules/knowledge` and `modules/policy` (version-gated load, atomic flush,
cross-process lock, disk read-back).

Two concepts that must never be conflated (contract §3.1):

* ``fingerprint``     — irreversible digest, **display only** ("is it configured?").
* ``credential_ref``  — opaque reference the *adapter runtime* uses to read the
  sealed secret through a controlled accessor.  A fingerprint can never be used
  to reconstruct the secret.
"""

from modules.model.credentials import (CredentialError, CredentialStore,
                                       CredentialInUse, KeyStoreError)
from modules.model.endpoint_policy import EndpointRejected, validate_endpoint
from modules.model.gating import enable_gate
from modules.model.registry import (ModelRegistry, ModelRegistryError,
                                    EvidenceMissing, FrozenModel, NotFound,
                                    Duplicate, CapExceeded, StoreUnavailable)

__all__ = [
    "CredentialStore", "CredentialError", "CredentialInUse", "KeyStoreError",
    "validate_endpoint", "EndpointRejected",
    "enable_gate",
    "ModelRegistry", "ModelRegistryError", "EvidenceMissing", "FrozenModel",
    "NotFound", "Duplicate", "CapExceeded", "StoreUnavailable",
]
