"""NAS-only partial backup. Never copies live mutable production directories.

Run on the NAS as the existing SSH user. All archives use AES-256-GCM;
keys are created separately under the user's private home. No secret output.
This does not establish application/data snapshot consistency.
"""
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CONTAINER = "xiaozhi-product-v1-sidecar"
EXPECTED_IMAGE = "sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611"
MAGIC = b"XZB6GCM1"


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise RuntimeError("Private directory permission check failed")


def encrypt_stream(source, target, key_path):
    key = os.urandom(32)
    with key_path.open("xb") as f:
        f.write(key)
        f.flush()
        os.fsync(f.fileno())
    nonce = os.urandom(12)
    header = MAGIC + nonce
    enc = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    enc.authenticate_additional_data(header)
    plain_sha = hashlib.sha256()
    size = 0
    with target.open("xb") as out:
        out.write(header)
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            plain_sha.update(block)
            out.write(enc.update(block))
        out.write(enc.finalize())
        out.write(enc.tag)
        out.flush()
        os.fsync(out.fileno())
    # Authenticate the complete archive immediately, without storing plaintext.
    dec_sha = hashlib.sha256()
    with target.open("rb") as f:
        actual_header = f.read(len(header))
        if actual_header != header:
            raise RuntimeError("Archive header mismatch")
        f.seek(-16, 2)
        tag = f.read(16)
        f.seek(len(header))
        dec = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        dec.authenticate_additional_data(header)
        remaining = target.stat().st_size - len(header) - 16
        while remaining:
            block = f.read(min(1024 * 1024, remaining))
            if not block:
                raise RuntimeError("Truncated ciphertext")
            remaining -= len(block)
            dec_sha.update(dec.update(block))
        dec_sha.update(dec.finalize())
    if dec_sha.digest() != plain_sha.digest():
        raise RuntimeError("Round-trip integrity failure")
    with target.open("rb") as f:
        cipher_sha = hashlib.file_digest(f, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else None
    if cipher_sha is None:
        h = hashlib.sha256()
        with target.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        cipher_sha = h.hexdigest()
    return {"file": target.name, "plaintext_bytes": size,
            "plaintext_sha256": plain_sha.hexdigest(),
            "ciphertext_sha256": cipher_sha,
            "ciphertext_bytes": target.stat().st_size,
            "aes256_gcm_authentication": True,
            "mode": oct(stat.S_IMODE(target.stat().st_mode))}


def main():
    os.umask(0o077)
    inspect_raw = subprocess.check_output(["docker", "inspect", CONTAINER])
    runtime = json.loads(inspect_raw)[0]
    if runtime["Image"] != EXPECTED_IMAGE or not runtime["State"]["Running"]:
        raise RuntimeError("Live production identity/state changed; abort")
    image_raw = subprocess.check_output(["docker", "image", "inspect", EXPECTED_IMAGE])
    image = json.loads(image_raw)[0]
    run_id = "b6-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # /volume1/docker is world-writable without a sticky bit. Use the
    # existing private SSH home, whose ancestors are root-owned 0755.
    root = Path.home() / ".xiaozhi-b6-backups"
    if not root.exists():
        private_dir(root)
    if root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o700 or root.stat().st_uid != os.geteuid():
        raise RuntimeError("Untrusted backup root")
    backup = root / run_id
    private_dir(backup)
    key_root = Path.home() / ".xiaozhi-b6-keys"
    if not key_root.exists():
        private_dir(key_root)
    if key_root.is_symlink() or stat.S_IMODE(key_root.stat().st_mode) != 0o700 or key_root.stat().st_uid != os.geteuid():
        raise RuntimeError("Untrusted separate key root")
    keys = key_root / run_id
    private_dir(keys)
    records = []
    saver = subprocess.Popen(["docker", "image", "save", EXPECTED_IMAGE], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        records.append(encrypt_stream(saver.stdout, backup / "production-image.tar.aesgcm", keys / "production-image.key"))
        saver.stdout.close()
        if saver.wait() != 0:
            raise RuntimeError("Docker image save failed; partial artifact retained")
    finally:
        if saver.poll() is None:
            saver.terminate()
            saver.wait()
    # Raw inspect can contain secrets: it never leaves authenticated encryption.
    records.append(encrypt_stream(io.BytesIO(inspect_raw), backup / "runtime-inspect.json.aesgcm", keys / "runtime-inspect.key"))
    records.append(encrypt_stream(io.BytesIO(image_raw), backup / "image-inspect.json.aesgcm", keys / "image-inspect.key"))
    final = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER]))[0]
    unchanged = all(final.get(k) == runtime.get(k) for k in ["Id", "Image", "RestartCount"])
    unchanged = unchanged and final["State"]["StartedAt"] == runtime["State"]["StartedAt"] and final["State"]["Running"]
    result = {"status": "PARTIAL", "run_id": run_id,
              "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "backup_directory": str(backup), "separate_key_directory": str(keys),
              "key_material_in_manifest": False, "backup_directory_mode": "0o700",
              "key_directory_mode": "0o700", "file_mode": "0o600",
              "cipher": "AES-256-GCM", "header": "XZB6GCM1 + 12-byte nonce; ciphertext; 16-byte GCM tag; header authenticated as AAD",
              "image_id": image["Id"], "architecture": image["Architecture"], "os": image["Os"],
              "rootfs_diff_ids": image["RootFS"]["Layers"],
              "container_id": runtime["Id"], "production_identity_and_start_unchanged": unchanged,
              "records": records,
              "not_backed_up": ["live Compose/env files", "full Secrets directory", "full data directory", "configuration/build dependencies outside image"],
              "consistency": "Immutable image and captured runtime specs only; no mutable-data backup or consistent snapshot claimed.",
              "independent_image_load": "NOT_PERFORMED"}
    with (backup / "MANIFEST.json").open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    with (backup / "SHA256SUMS").open("x") as f:
        for record in records:
            f.write(record["ciphertext_sha256"] + "  " + record["file"] + "\n")
        f.write(hashlib.sha256((backup / "MANIFEST.json").read_bytes()).hexdigest() + "  MANIFEST.json\n")
        f.flush()
        os.fsync(f.fileno())
    for directory in [backup, keys, root, key_root]:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
