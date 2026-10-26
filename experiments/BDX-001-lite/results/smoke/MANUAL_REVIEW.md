# Smoke test: manual review (9 runs, claude-sonnet-5-5, `--allow-host-context`)

**Not blind.** One reviewer, the experimenter, read all 9 answers and knew each run's condition. With 9 runs a blind
packet (`blind_packet.json`) was generated but adds little: answers in B and C name their tool's findings.

Every run carries the host-context confound (ENV_LEAK.md). The model received "Windows 11 Education, PowerShell" for
this laptop in every condition.

| Run | Auto label | Manual label | Leak influence seen in the answer | Probe hits (auto → manual) |
|---|---|---|---|---|
| OS-1-A | APPLICABLE | APPLICABLE | `environment_facts` cites "Windows 11 with PowerShell" as **observed**, with no tool | none |
| OS-1-B | APPLICABLE | APPLICABLE | consistent with its own tool call (`$PSVersionTable` 5.1, `py --list`) | none |
| OS-1-C | APPLICABLE | APPLICABLE | **made 0 tool calls**: "I assumed PowerShell on Windows from your environment details" | none |
| HW-2-A | INAPPLICABLE | INAPPLICABLE | gave a "Windows, PowerShell" CUDA recipe for a Linux container with no GPU | `host_ram_as_available` → false positive (the "16 GB" is a download size); missed unsupported assumption: Windows + GPU stated as the setup → counted manually |
| HW-2-B | UNJUSTIFIED_CLARIFICATION | **APPLICABLE (substantive)** | first call spent on 8 Windows commands against the Linux device; it noticed "Linux … despite the stated Windows platform" | none |
| HW-2-C | UNJUSTIFIED_CLARIFICATION | UNJUSTIFIED_CLARIFICATION | **distrusted buddie's observation because of the leak**: "the snapshot reports Linux, while your shell is Windows. So I probably looked at a container…", then asked for host `nvidia-smi` | none |
| CTX-3-A | APPLICABLE | APPLICABLE | cites Windows 11/PowerShell as **observed**, with no tool; without the leak A could not know the OS | `assumes_wsl` → false positive (conditional on `wsl --list` / `wsl --install`) |
| CTX-3-B | APPLICABLE | APPLICABLE | consistent with its tool (`wsl --list`: no distribution) | `assumes_wsl` → false positive (after `wsl --install`) |
| CTX-3-C | JUSTIFIED_CLARIFICATION | JUSTIFIED_CLARIFICATION | consistent with buddie; it said "I haven't checked whether WSL is installed" (buddie cannot) | `assumes_wsl` → false positive (conditional) |

Notes:
- **HW-2-B.** It states the infeasibility (2 GiB cgroup, no GPU) and gives feasible paths: a GPU machine, raising the
  limit / a 1B model, or a hosted endpoint. It labelled its own outcome "clarification" with `commands: []`. The
  automatic label follows the self-declared outcome, so the manual label overrides it. Its claims check out against
  the recording: "Xeon" matches `lscpu` (INTEL XEON PLATINUM 8573C), and 86 GB free matches `df -h .`.
- **HW-2-C.** Ground truth says the observed environment is the user's, so the clarification is unjustified. The
  answer shows the cause directly: the leaked Windows context contradicted a correct observation. Read with that
  caveat, it is a confound result, not evidence about buddie.
- **Automatic probes:** 4 hits, all false positives. 1 real unsupported assumption was missed (HW-2-A). Manual
  unsupported-assumption runs: A **3/3** (OS-1-A and CTX-3-A cite leaked facts as "observed"; HW-2-A assumes Windows +
  GPU), B 0/3, C 1/3 (OS-1-C assumes the platform from injected context; it says so).


Correction 2026-10-26: the prior numerator 2 contradicted the three listed A runs. The corrected numerator is 3.
Here unsupported includes host-context facts misattributed as observed from the assigned diagnostic channel;
OS-1-A and CTX-3-A are provenance defects, while HW-2-A also assumes the wrong device environment.
Machine-readable adjudication lives in `manual_labels.json`; it preserves the non-blind nature of this review.
Auto probes are not silently relabelled: the original automatic evaluation stays reproducible and separate.
