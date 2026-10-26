# Public release records

`releases/<version>.json` is the authoritative public release text. The record is committed and reviewed before
candidate creation. It contains exactly `schema`, `version`, `date`, `summary`, `changes`, `upgrade`, `permissions`,
`security` and `limitations`; duplicate/unknown keys, empty content, invalid dates and mismatched versions fail.
The development record for 2.0.2 is a review draft. Its date is a planned record date, not evidence of publication.
Published PyPI 2.0.1 files are never replaced.

Edit the record, generate its descriptions, and commit the generated `packaging/README.md` alongside it. The
candidate workflow compares that file with the generator before building. Human review must check that the
text is public, accurate and limited to shipped behavior: path allowlists cannot determine whether prose is
private or whether a claim is true.

```sh
python scripts/release_notes.py --version 2.0.2 --out rc/metadata
```

Use a fresh output directory when reviewing a candidate. The generator uses UTF-8 and LF, with a fixed channel
and section order. It has no network calls or publication behavior. The source commit is recorded later in
`release-manifest.json`, avoiding a circular commit reference inside the source record.

## Candidate binding

Candidate schema `buddie-release-candidate-v2` requires the generated Markdown, public record, Registry payload
and channel descriptions in `metadata/`, in addition to the runtime artifacts and compact-plugin manifest.
Every file is hashed in the release manifest and SHA256SUMS. Verification loads the release record and
`server.json` from Git blobs at the exact recorded commit and compares rendered metadata against those inputs.
Coherently replacing the candidate's notes and checksums while retaining the claimed commit is refused.

The source repository at the recorded revision must be available to the verifier. Hashes prove byte identity;
the existing workflow authorization establishes which CI run/source revision the operator approved. Old tagged
release workflows retain their historical candidate schema. New candidates cannot silently omit public notes.

## Channel adapters

- **GitHub:** publish the exact candidate Markdown. Existing drafts and published releases with another body
  are refused; there is no version-only fallback or automatic description replacement.
- **PyPI:** `packaging/README.md` is the version-specific description in both wheel and sdist. The built core
  metadata is checked for the public text, MCP Registry marker, version, summary, project links and legal/privacy
  fields. The full source README and changelog are excluded from the sdist. Existing package metadata and entry
  points are retained; no separate PyPI release-note API is assumed.
- **MCP Registry:** the candidate's supported publisher-provided `_meta` namespace carries a canonical note URL,
  version and digest. The generated payload is validated against the declared official schema. This does not
  establish that a downstream catalog displays the fields.
- **Claude plugin:** Git-blob packaging generates a public README and RELEASE_NOTES.md; the manifest fields and
  launchers retain their supported format. The release JSON and development material are not shipped.
- **Claude Desktop MCPB:** the public versioned README and RELEASE_NOTES.md accompany the unchanged manifest
  format. Runtime archive checks and installed smoke remain separate gates.
- **Codex:** a channel description is generated, but its minimal package and trusted hooks require the separate
  Codex profile. The Claude package is not evidence of Codex installation compatibility.

Candidate creation publishes nothing. Package publication, tags, distribution-branch promotion, catalog account
changes and paid experiments retain their separate authorization requirements. A note URL or generated payload
is never reported as successful observed delivery by itself.
