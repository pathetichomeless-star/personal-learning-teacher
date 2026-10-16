"""Read-only NAS verification. No Docker operations, extraction or plaintext output."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"XZB6GCM1"
CHUNK = 1024 * 1024


def require(ok):
    if not ok:
        raise RuntimeError("Verification assertion failed")


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def private(path, directory=False):
    s = path.lstat()
    require(not path.is_symlink() and s.st_uid == os.geteuid())
    require(stat.S_IMODE(s.st_mode) == (0o700 if directory else 0o600))
    require(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode))


def decrypt_blocks(path, key_path, bad_tag=False):
    key = key_path.read_bytes()
    require(len(key) == 32)
    with path.open("rb") as f:
        header = f.read(20)
        require(len(header) == 20 and header[:8] == MAGIC)
        f.seek(-16, 2)
        tag = f.read(16)
        if bad_tag:
            tag = bytes([tag[0] ^ 1]) + tag[1:]
        dec = Cipher(algorithms.AES(key), modes.GCM(header[8:], tag)).decryptor()
        dec.authenticate_additional_data(header)
        remaining = path.stat().st_size - 36
        require(remaining >= 0)
        f.seek(20)
        while remaining:
            b = f.read(min(CHUNK, remaining))
            require(bool(b))
            remaining -= len(b)
            yield dec.update(b)
        yield dec.finalize()


class DecryptedReader(io.RawIOBase):
    def __init__(self, blocks):
        super().__init__()
        self.blocks = iter(blocks)
        self.pending = b""
        self.sha = hashlib.sha256()
        self.count = 0

    def readable(self):
        return True

    def readinto(self, target):
        while not self.pending:
            try:
                self.pending = next(self.blocks)
            except StopIteration:
                return 0
        n = min(len(target), len(self.pending))
        target[:n] = self.pending[:n]
        self.sha.update(self.pending[:n])
        self.count += n
        self.pending = self.pending[n:]
        return n


def main():
    root, keys = (Path(v) for v in sys.argv[1:3])
    require(len(sys.argv) == 3 and root.is_absolute() and keys.is_absolute())
    for p in (root, root.parent, keys, keys.parent):
        private(p, True)
    require(root.resolve() != keys.resolve())
    require(root.resolve() not in keys.resolve().parents)
    private(root / "MANIFEST.json")
    private(root / "SHA256SUMS")
    manifest = json.loads((root / "MANIFEST.json").read_bytes())
    checksums = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        require(Path(name).name == name and name not in checksums)
        checksums[name] = digest
    records = manifest["records"]
    require(set(checksums) == {r["file"] for r in records} | {"MANIFEST.json"})
    for name, digest in checksums.items():
        private(root / name)
        require(sha_file(root / name) == digest)
    authenticated = {}
    small_plain = {}
    by_name = {}
    for record in records:
        name = record["file"]
        require(Path(name).name == name and name.endswith(".aesgcm"))
        by_name[name] = record
        key = keys / (name.removesuffix(".aesgcm").removesuffix(".tar").removesuffix(".json") + ".key")
        private(key)
        require((root / name).stat().st_size == record["ciphertext_bytes"])
        require(checksums[name] == record["ciphertext_sha256"])
        digest, count = hashlib.sha256(), 0
        parts = []
        for block in decrypt_blocks(root / name, key):
            digest.update(block)
            count += len(block)
            if name.endswith(".json.aesgcm"):
                require(count <= CHUNK)
                parts.append(block)
        require(digest.hexdigest() == record["plaintext_sha256"] and count == record["plaintext_bytes"])
        authenticated[name] = True
        if parts:
            small_plain[name] = json.loads(b"".join(parts))
        rejected = False
        try:
            for _ in decrypt_blocks(root / name, key, bad_tag=True):
                pass
        except InvalidTag:
            rejected = True
        require(rejected)

    expected = small_plain["image-inspect.json.aesgcm"][0]
    runtime = small_plain["runtime-inspect.json.aesgcm"][0]
    require(expected["Id"] == manifest["image_id"] == runtime["Image"])
    require(runtime["Id"] == manifest["container_id"])
    require(expected["RootFS"]["Layers"] == manifest["rootfs_diff_ids"])
    require(expected["Architecture"] == manifest["architecture"] == "arm64")
    require(expected["Os"] == manifest["os"] == "linux")
    image_path = root / "production-image.tar.aesgcm"
    original_stat = image_path.stat()
    raw = DecryptedReader(decrypt_blocks(image_path, keys / "production-image.key"))
    stream = io.BufferedReader(raw)
    hashes, json_objects = {}, {}
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            p = PurePosixPath(member.name)
            require(not p.is_absolute() and ".." not in p.parts)
            if not member.isfile():
                continue
            require(member.name not in hashes)
            f = archive.extractfile(member)
            h = hashlib.sha256()
            first = f.read(2)
            h.update(first)
            parts = [first] if member.size <= CHUNK else None
            # Current Docker save uses uncompressed layer blobs. Compressed
            # layers fail the exact diff-ID assertion rather than being skipped.
            for block in iter(lambda: f.read(CHUNK), b""):
                h.update(block)
                if parts is not None:
                    parts.append(block)
            hashes[member.name] = h.hexdigest()
            if parts is not None:
                try:
                    json_objects[member.name] = json.loads(b"".join(parts))
                except (ValueError, UnicodeDecodeError):
                    pass
    # Tar readers stop at the end marker; drain to authenticate second pass.
    for _ in iter(lambda: stream.read(CHUNK), b""):
        pass
    rec = by_name["production-image.tar.aesgcm"]
    require(raw.sha.hexdigest() == rec["plaintext_sha256"] and raw.count == rec["plaintext_bytes"])
    final_stat = image_path.stat()
    require((original_stat.st_dev, original_stat.st_ino, original_stat.st_size, original_stat.st_mtime_ns) ==
            (final_stat.st_dev, final_stat.st_ino, final_stat.st_size, final_stat.st_mtime_ns))
    docker_manifest = json_objects["manifest.json"]
    require(len(docker_manifest) == 1)
    entry = docker_manifest[0]
    config = json_objects[entry["Config"]]
    config_digest = "sha256:" + hashes[entry["Config"]]
    require(config_digest == expected["Id"])
    require(config["architecture"] == "arm64" and config["os"] == "linux")
    require(config["rootfs"]["diff_ids"] == expected["RootFS"]["Layers"])
    require(len(entry["Layers"]) == len(expected["RootFS"]["Layers"]))
    actual_layers = ["sha256:" + hashes[name] for name in entry["Layers"]]
    require(actual_layers == expected["RootFS"]["Layers"])
    # Every content-addressed OCI blob must also match its stored blob name.
    blob_count = 0
    for name, digest in hashes.items():
        if name.startswith("blobs/sha256/"):
            require(name.split("/")[-1] == digest)
            blob_count += 1
    print(json.dumps({
        "status": "OFFLINE_INTEGRITY_PASS_ONLY",
        "backup_directory": str(root),
        "manifest_sha256": checksums["MANIFEST.json"],
        "ciphertext_sha256_checks": len(records),
        "authenticated_archives": authenticated,
        "tampered_tag_rejected_count": len(records),
        "image_plaintext_sha256": rec["plaintext_sha256"],
        "image_plaintext_bytes": raw.count,
        "archive_config_digest": config_digest,
        "image_inspect_and_runtime_identity_match": True,
        "architecture": "arm64", "os": "linux",
        "ordered_layer_hashes_match": True, "layer_count": len(actual_layers),
        "verified_oci_blob_count": blob_count,
        "no_plaintext_extracted": True, "no_docker_operations": True,
        "independent_image_load": "NOT_PERFORMED",
        "data_secrets_policy_runtime_restore": "BLOCKED_NOT_PERFORMED"
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never surface raw JSON values, environment or ciphertext internals.
        print(json.dumps({"status": "OFFLINE_VERIFICATION_FAILED", "details": "suppressed to protect production metadata"}))
        sys.exit(1)
