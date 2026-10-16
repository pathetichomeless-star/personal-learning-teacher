# B6 Agent C — Exact Restore

Status: **BLOCKED / preparation only**. No restored instance, network, or data volume has been started. No independent Docker image load has occurred. This document does not assert a successful restore.

## Independently observed evidence

Read-only SSH checks on `xiaozhi-nas`, 2026-10-10 Asia/Shanghai:

- NAS Docker server: `29.6.2`; storage driver `overlay2`; daemon root `/volume1/@docker`.
- Inspected image: `sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`; OS `linux`; architecture `arm64`; 13 RootFS layers; image user `10001`. This inspection corroborates the image object only; Production Inventory must establish the live container-to-image binding.
- Production network `xiaozhi-product-v1_default`: bridge, `Internal=false`, 1 attached container. It must never be reused for restore testing.
- NAS account is UID 1000, member of the Docker group. `dockerd`, `containerd`, `ctr`, `unshare`, Python 3, OpenSSL and SHA-256 tooling exist.
- Rootless runtime prerequisites `rootlesskit`, `slirp4netns`, `newuidmap`, `newgidmap` are absent from PATH and the checked `/usr/bin` locations; `dockerd-rootless.sh` is absent there. Existence of `/etc/subuid` and `/etc/subgid` does not establish configured mappings or a working rootless daemon.
- The local workstation has no Docker executable in PATH. No local image archive was transferred.

No environment values, secret file bytes, raw container inspect output, tokens, or decryption material were displayed.

## Blocking prerequisites

1. Lead reported that the production data filesystem is ext4, Btrfs probing failed, LVM tooling is unavailable, and noninteractive sudo is unavailable. A proven application-consistent filesystem snapshot is unavailable. Agent C has not independently repeated the filesystem probe and does not claim independent verification of that particular finding.
2. An application-consistent data, configuration and Secrets archive has not been supplied. A plain copy of live mutable files cannot satisfy this gate; repeated matching hashes do not prove a cross-file consistent snapshot.
3. An independent NAS-only Docker image store has not been established. Loading an archive into the already populated production daemon would not prove independent recovery and could alter the production image/tag store. Starting an additional rootful daemon, installing prerequisites, using a privileged helper, or transferring the archive away from the NAS is outside this implementation path.

Consequently image load, secure payload decryption, numeric ownership/ACL/xattr restoration, PolicyStore recovery, authentication/static asset checks and voice assembly restoration remain **NOT EXECUTED**. Offline archive verification, if completed by the backup agent, is useful integrity evidence but must not be labelled Docker load or exact restore.

## Safe execution design after prerequisites are resolved

All steps below are a future procedure, not recorded results. Any production pause requires separate product-owner authorization. Independent test capacity and a verified consistent backup are required first.

1. Use a new independent Docker daemon/context on the NAS with its own image store, state directory and socket. Abort if its daemon ID, root directory or socket resolves to the production engine. No external image pulls or third-party upload. Load the saved archive there and require the resulting full image ID, OS/architecture and ordered RootFS diff IDs to equal the frozen production image metadata.
2. Verify every encrypted archive SHA-256 before decryption. Decrypt through a controlled private pipe or protected NAS-only directory using separately managed key material. No command-line secret arguments, echoed environment values, shell tracing or ordinary logs. Verify payload authentication and the protected plaintext inventory before extraction; a decrypt exit code alone is insufficient for unauthenticated encryption modes.
3. Extract only into newly created test volumes. Reject archive absolute paths, traversal and unsafe link targets before extraction. Compare all restored relative paths, regular-file SHA-256, file types, numeric UID/GID, mode, symlink targets, hardlinks, ACLs, xattrs and supported timestamps against the snapshot inventory. Treat inode and ctime changes as expected restoration differences, not preserved metadata. Do not trim old history, exclude unexpected files or overwrite production paths.
4. Verify configuration and Secrets bytes/metadata privately, then mount only restored test paths. Secrets mount must be read-only; ownership and minimal access modes must match the snapshot. Recovered Compose and effective runtime specification must be compared field by field, including mounts, user, entrypoint/command, restart/resource/security settings, ports, environment references and healthcheck. Real values remain in the protected recovery bundle.
5. Use `--network none` for the test application, a unique container name, no published ports, no production networks, no host networking, no host/PID/IPC namespaces and no Docker socket mount. This is stronger than relying on `internal: true` alone, which does not by itself prove that host services are unreachable. Inspect network attachment and container routing before starting the actual application. Use a harmless preflight process first; the application must not run until its only interface is loopback, no non-loopback route exists and production/LAN/public connections fail.
6. After isolation proof, start a local Mock Qwen and Mock Workbench inside the test container network namespace, reachable only through loopback. Force `QWEN_MODE=mock`, `QWEN_WS_URL` to that loopback endpoint and `WORKBENCH_BASE_URL` to its loopback mock; inventory every other cloud/production URL in recovered runtime values and replace or disable it. Actual recovered Secrets remain privately verifiable but must not be sent to a mock, request log or test report. Record these explicit safety substitutions: they mean the test validates recoverable runtime assembly and original configuration integrity, without exercising real cloud credentials.
7. Execute probes using the independent daemon's `docker exec` and loopback endpoints, without exposing a host port. Compare original static resource hashes with the restored image/resources. Assert the current production version's actual authenticated/unauthenticated behavior and loaded data, not candidate ADMIN P0 expectations or only HTTP 200. Read the recovered admin token only within the test process and print booleans/status codes rather than the token or response bodies.
8. Before application startup, compare complete PolicyStore bytes plus canonical hashes of `active`, every `history` record and every `audit` record with the frozen snapshot. Inside the recovered production image, load its own `PolicyStore` implementation and assert schema, active version/content hash, exact ordered history and complete audit equality. Compare the in-memory loaded policy with the snapshot, not merely file existence or API availability. Repeat after restart of the test instance; no production restart is allowed.
9. Exercise the voice handshake and mock protocol from loopback, checking configured model/voice and recorded mock connection/session-update counters without logging instructions or personal content. Confirm restored files remain unchanged after read-only probes. Any intentional test writes use a second disposable copy and must not change the pristine restored baseline.
10. Independent QA rechecks the encrypted manifest, archive provenance, image identity, actual isolation evidence, loaded PolicyStore state and metadata comparisons. Production pre/post image ID, container ID, StartedAt and connection/service evidence must be compared independently. Publish only sanitized results.

## PolicyStore fail-soft risk

Local source `modules/policy/persona.py`, `PolicyStore.load()`, initializes built-in version 1 and empty history/audit, then silently retains that state when the file is missing, schema differs or content cannot load. `gateway/app/admin/stores.py` also tolerates degraded stores. Thus a healthy container, HTTP 200 or a non-null policy object does not establish recovery. The restored **production image's** implementation and loaded active/history/audit must be checked explicitly; the local candidate source is only a risk signal, not proof of production behavior.

PolicyStore audit in the persistent policy document and the separate in-memory `AdminAudit` are distinct. The latter is process memory and cannot be recovered by a disk archive; the actual production implementation and acceptance scope must be identified rather than promising recovery of transient state.

## Boundary and rollback implications

The previous `RELEASE_SAFETY.md` refers to historical `34ea8277...`; that historical rollback command is invalid as the exact ADMIN-V2 rollback target. A future rollback must pin the complete live image identity established by this B6 inventory, use the authenticated original runtime bundle and restore consistent data only under a separately approved maintenance window. Snapshot-time data restoration can discard later memory, knowledge, policy/history/audit and other writes. Preserve a current consistent backup and decide retention/reconciliation before any rollback; do not assume current data is backward compatible with a prior image.

## Executed offline archive verification

The Lead supplied actual NAS backup `/home/<nas-login>/.xiaozhi-b6-backups/b6-20261009T190033Z` and its separate private key directory. Agent C ran `b6_offline_verify.py` over SSH on the NAS; script source was passed on stdin. No plaintext archive left the NAS or was extracted. This is a separately implemented verifier, not a repetition of the backup script's self-check.

- Three encrypted archives independently passed ciphertext SHA-256, AES-256-GCM authentication with header AAD, plaintext SHA-256 and size validation. Every modified-tag negative test was rejected (3/3).
- The second image decryption stream was parsed only after full initial authentication, then fully drained and authenticated again. Archive bytes: `179633664`; SHA-256: `62d00b6b7ad32b6a77fc5b0dac51d8485c2b84fc6b90f750deba45c5da2ceb01`.
- Docker archive configuration content SHA-256 equals `sha256:038d2f6c7a8945ff8ceadffdf100dc306123d51aa8b0ad2c4c48ed073b826611`, matching encrypted image-inspect and runtime-inspect identities. Architecture/OS: `linux/arm64`.
- All 13 ordered layer tar SHA-256 values equal the frozen RootFS diff IDs. All 28 content-addressed OCI blobs match their path digests.
- Protected directories and files passed current UID ownership and `0700`/`0600` checks. Manifest SHA-256: `37afd3bd8cb636ce302bc5d63b4b82d4a65938990c4198e66da1ee51b0a54994`.
- No Docker operations, no container start, no plaintext extraction and no cloud connection were performed by this verifier.

Sanitized machine result: `AGENT_C_OFFLINE_RESULT.json`. Scope is **OFFLINE_INTEGRITY_PASS_ONLY**. This establishes encrypted image archive integrity and identity, but cannot establish successful Docker loading, image runtime behavior, full configuration/Secrets/data recovery or PolicyStore restoration. It does not alter any BLOCKED recovery gate above.

Agent C result: **BLOCKED**, offline image integrity passed; no independent exact-restore PASS and no deployment authorization.
