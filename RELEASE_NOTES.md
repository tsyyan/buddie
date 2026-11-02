# buddie 2.0.8

2026-11-02

Environment diagnostics you can turn on in one step, Docker and Podman client versions in the baseline, and a skill that asks for the machine's facts before suggesting commands.

## Changes

- /buddie:init offers the environment diagnostics as a separate question and, only if the person agrees, writes a grants file with the baseline categories; a second, separate question covers the Docker daemon.
- New buddie snapshot --grant-baseline writes that grants file where buddie reads it, baseline only, never over an existing file.
- New baseline category software.containers: docker --version and podman --version only, no daemon is contacted; asking the daemon stays development.containers, sensitive.
- New environment skill: before suggesting commands for the person's own machine, ask environment_snapshot for the categories those commands depend on, and do not guess what was denied.
- docs/environment.md opens its diagnostics section with a short account of who decides, when the agent asks and what comes back; docs/research.md reports BDX-003, whether buddie changes what reaches the reader.

## Upgrade

Install buddie==2.0.8 or update the plugin. The Claude Code marketplace follows plugin-stable and receives this release after publication; no reinstall is needed. Existing grants files keep working; development.containers in them still covers the clients too.

## Permissions

No new runtime permissions or dependencies. Diagnostics observe only categories the person granted in their own grants file; the new baseline category runs two programs' --version. Checks run locally without a model. Optional evidence checks request cited URLs and the GitHub API (api.github.com, or an administrator-approved Enterprise API); GitHub credentials stay optional. No report or transcript is sent to a Buddie collection service.

## Security

Python hooks still run with -I and require Python 3.11 or newer. The candidate binds archives and public metadata to the source revision and SHA-256 digests. Report vulnerabilities through SECURITY.md.

## Limitations

Checks support evidence review and do not establish that every claim is true. Local source snapshots, pending report lines and feedback state can contain personal data and have no automatic expiry; the person can delete them. See PRIVACY.md for controls. Passing automated directory validation does not imply Anthropic approval; publication in its directory requires a separate review.
