"""What one hook event resolves to before anything is checked: the repos around it, their buddie.toml, and the
settings with their sources. Built once per event by the hook's main path and handed to what it calls, so the
repos are looked up (one `git rev-parse`) and each buddie.toml is read once, where the hook used to do both four to
six times per Stop.

It holds what the event *configures*, not what the machine *is*: no network, no store, no transcript is touched to
build it. Each value comes out as the reader it replaces gave it (config.of_event, config.final_mark,
mandate.find_config): the same first-file rules, the same treatment of a file that does not parse. Its sources keep
config.Source: buddie.toml is REPO (the agent can write it), the environment and plugin settings USER.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from buddie import config


@dataclass(frozen=True)
class ResolvedEventContext:
    event: dict
    session: str | None
    repos: tuple[Path, ...]
    config_path: Path | None              # config.find: the first repo with a buddie.toml
    config: dict                          # config.load of it ({} when it does not parse)
    levels: dict[str, config.Setting]
    transcript: config.Setting
    journal_text: bool
    final_mark: str | None                # config.final_mark
    mandate: dict                         # for verify(mandate=): the [mandate] config found, {} when no usable
                                          # repo has one (verify then judges no work claims, as find_config's None did)
    files: dict[Path, object] = field(default_factory=dict, repr=False)  # repo -> parsed buddie.toml / ConfigError
    config_errors: tuple[config.ConfigError, ...] = ()  # each buddie.toml that exists but cannot be used

    @property
    def configured(self) -> bool:
        return self.config_path is not None

    @property
    def level(self) -> dict[str, str]:
        return {k: s.value for k, s in self.levels.items()}

    def with_event(self, event: dict) -> "ResolvedEventContext":
        """The same resolution for an event the hook rewrote (transcript paths dropped when reading is off)."""
        return ResolvedEventContext(event, self.session, self.repos, self.config_path, self.config, self.levels,
                                    self.transcript, self.journal_text, self.final_mark, self.mandate, self.files,
                                    self.config_errors)


def _read(repos) -> dict[Path, object]:
    files: dict[Path, object] = {}
    for repo in repos:
        path = repo / config.CONFIG
        if not path.is_file():
            continue
        try:
            files[repo] = config.read_toml(path)
        except config.ConfigError as error:
            files[repo] = error
    return files


def resolve(event: dict, repos: list[Path] | None = None) -> ResolvedEventContext:
    from buddie import mandate
    from buddie.event import repos_of
    repos = tuple(repos if repos is not None else repos_of(event))
    files = _read(repos)
    # a file that cannot be used counts as there (the full defaults apply, not the fresh-install ones) and gives
    # nothing: no level, no final mark, no [mandate] regex is taken from it; config_errors says so, and the gate
    # returns the answer until it is fixed or disclosed
    errors = tuple(f for f in files.values() if isinstance(f, config.ConfigError))
    usable = {r: f for r, f in files.items() if isinstance(f, dict)}
    first = next((r for r in repos if r in files), None)
    path = first / config.CONFIG if first is not None else None
    cfg = usable.get(first, {}) if first is not None else {}
    mark = os.environ.get("BUDDIE_FINAL")
    if mark is None:
        mark = next((m for r in repos if r in usable
                     and (m := usable[r].get("mandate", {}).get("final_mark")) is not None), None)
    man: dict = next(({**mandate.DEFAULTS, **usable[r]["mandate"], "repo": str(r)} for r in repos
                      if r in usable and usable[r].get("mandate") is not None), {})
    return ResolvedEventContext(event, event.get("session_id"), repos, path, cfg,
                                config.resolve_levels(cfg, path is not None), config.resolve_transcript(cfg),
                                config.journal_text(cfg), mark, man, files, errors)
