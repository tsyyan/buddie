# Security policy

## Reporting a vulnerability

Please do not put exploit details, credentials, private reports, transcripts or source snapshots in a public issue.

If GitHub shows **Report a vulnerability** on this repository's
[Security advisories page](https://github.com/tsyyan/buddie/security/advisories), use that private form.
If the button is unavailable, open a public issue asking only for a private reporting channel, without vulnerability
details. There is currently no published security email address. Do not send sensitive material until a private
channel has been agreed with the maintainer.

In a private report, include the affected version or commit, client and installation method, operating system,
a minimal reproduction with synthetic data, expected and actual behavior, and the security impact.
Redact tokens, private repository names and personal information.

## Versions and handling

Start by checking the latest [published release](https://github.com/tsyyan/buddie/releases/latest).
Reports about older releases and unreleased commits are welcome; there is no promise of backports or a fixed
response deadline. The maintainer will assess scope, coordinate a fix and agree disclosure with the reporter.

## Boundaries

buddie checks evidence behind reports. A passing receipt does not establish factual truth, intent or the safety of
the software being checked. The checker is not a sandbox for an agent running as the same OS user.

- [Execution boundaries, findings and remaining limits](docs/security.md)
- [Protected policy](docs/policy.md)
- [Privacy and stored data](PRIVACY.md)
- [Architecture and evidence provenance](docs/architecture.md)

For ordinary bugs, feature requests and installation questions, use [Issues](https://github.com/tsyyan/buddie/issues).
