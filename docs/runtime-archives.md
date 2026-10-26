# Runtime archive gate

Run `python scripts/check_runtime_archive.py ARCHIVE...` before extraction or installation. Supported formats are the wheel, gzipped sdist, MCPB, and the existing compact Claude plugin ZIP. This is file-selection verification; manifest compatibility, source provenance, content review and runtime smoke checks remain separate gates.

The policy names every runtime module, launcher, hook, skill, command, metadata file and legal/privacy document explicitly. Every runtime module is mandatory. The wheel requires its single versioned metadata directory, entry points, RECORD, LICENSE, NOTICE and PRIVACY.md; its README is carried in METADATA. The sdist requires its single versioned root, build metadata, source metadata and legal/privacy files. MCPB and plugin require their existing manifests, launchers, README and legal/privacy files. The plugin keeps both hooks, both skills and all three commands. MCPB alone may additionally contain SECURITY.md.

Paths must be bounded plain relative POSIX paths. The gate rejects duplicate entries, casefold collisions in every component (including implicit parents), files used as directories, Windows device names, unknown/empty directories, links, special files, encrypted ZIP entries and unreviewed ZIP extra fields that can encode Unix links. The approved builders emit no ZIP extra fields. Only ancestors of approved files may be explicit directories; the compact plugin format has no directory entries. Counts and declared sizes are bounded. The checker never extracts or runs an archive.

The previous runtime-only patch was independently reviewed against main `0a638d354c03cc44ea806a72547d084c122cd034`. Its broad Python glob admitted arbitrary runtime-directory files, required metadata/legal checks were absent, directory/component collisions were not checked, and compact plugin ZIP was unsupported. This implementation replaces those rules instead of applying that patch.

For ZIP formats the gate also reads approved members in bounded chunks to validate their CRCs and agreement
between local headers and the central directory. It rejects a local traversal filename hidden behind an approved
central-directory path before extraction or installation. No archive bytes are executed by this check.
Only STORED and DEFLATE are accepted. Complete decompressed size, CRC and end-of-stream are checked independently
of the declared size; all local extra fields are refused. Local records must cover the archive's data area exactly,
so hidden unindexed entries, prefixes and trailing payloads cannot bypass the inventory. Ordinary streaming data
descriptors remain supported and are checked against the directory. Approved builders emit no global ZIP comment.

## Validation

`python -m pytest -q tests/test_runtime_archive.py` exercises approved archives, every mandatory-file omission, unknown Python modules, research/private paths, traversal/absolute/Windows paths, links, special types, duplicate entries, component collisions, unsupported ZIP metadata, size limits, corrupt archives and multiple sdist roots.

`python -m build --outdir DIST` followed by `python scripts/check_clean_archives.py DIST` checks both archives before installing either, creates separate temporary environments, and runs the existing entry-point, MCP and offline verification smoke from outside the source checkout. CI runs these checks and MCPB/plugin checks and unpacked smoke on Linux, macOS and Windows. The candidate workflow still performs Claude CLI validation and isolated actual plugin installation on Linux.

## Baseline inventory comparison

Local Windows builds from the base and this change were inventoried without extraction, with exact paths, sizes and SHA-256 for every member and archive. Binary build output and environment logs stay outside the repository; they are review evidence, not release artifacts or permission to replace PyPI 2.0.1. Setuptools 84.2.1, build 1.6.1 and MCPB 2.1.2 were used.

The public [machine-readable inventories](maintenance/runtime-archive-inventories.json) record exact before/after
member paths, sizes, hashes and build source commits for all four formats. Local workspace paths are omitted;
the binary review builds remain outside the repository and are not published package replacements.

| Format | Before files | After files | Selection change |
| --- | ---: | ---: | --- |
| Wheel | 57 | 58 | Add `*.dist-info/licenses/PRIVACY.md` |
| sdist | 66 | 66 | No member-path changes; explicit pruning of experiments/private evidence |
| MCPB | 63 | 58 | Remove three `assets/brand` images and two `assets/demo` SVGs |
| Compact Claude plugin | 66 | 66 | Existing runtime layout preserved |

The tarballs also contain four approved parent-directory entries. Packaging metadata/content hashes change where configuration changes; timestamps mean ordinary wheel/sdist/MCPB rebuild bytes are not claimed reproducible. The compact plugin retains its deterministic byte-for-byte rebuild check.

## Extending the policy

A new module or public release file needs an exact entry and mandatory-file decision in `scripts/check_runtime_archive.py`, an adversarial/positive test, rebuilt inventories and clean smoke. There is no wildcard escape hatch. Future generated `RELEASE_NOTES.md` belongs in the MCPB/plugin exact sets only after those channel builders actually emit it. The generated PyPI `packaging/README.md` and any build-support module belong in the sdist exact set only after their final paths are established and an sdist-only clean build proves they are needed. Review accompanying MANIFEST.in/.mcpbignore changes and the compact plugin builder's selection separately. No future files are approved by this change.
