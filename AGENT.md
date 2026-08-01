# listen-gen Agent Guide

## First read

Before changing this repository, read these files completely in order:

1. `AGENT.md`
2. `CONTEXT.md`
3. `ECOSYSTEM.md`
4. `README.md`

Treat the current code, the living ecosystem context, and the canonical Core
contract as authoritative. Do not infer current behavior from an old ADR or a
future-state design. Keep cross-repository boundary or contract changes
coordinated rather than changing one repository's interpretation silently.

## Mission

Generate expensive, reusable language-learning resources and package them for
`listen-core`. Keep model/provider implementations replaceable and keep the
exchange contract stable.

## Contract ownership

- `listen-core/contracts/content-package/v1` is the only schema authority.
- Do not copy the schema into this repository.
- Update `contracts.lock.json` when the pinned schema identity/version changes.
- Package output must contain only typed, allowlisted resources.

## Safety and privacy

- Never include local filesystem paths, secrets, raw provider responses, or
  learner facts in a package.
- Unknown LLTimeline artifacts produce warnings; never forward their payloads.
- Tests must be deterministic and must not use paid/live model calls.

## Scope discipline

The compatibility converter is not the production pipeline. Do not copy the
old `timeline-production` tree here. Move generation capabilities in coherent
later slices behind the package contract.

`ECOSYSTEM.md` defines this repository's product boundary. In particular,
catalog and registry services, package installation and active selection,
learner records, learning UI, and learner-dependent real-time capabilities do
not belong in `listen-gen`.

## Git

- Preserve unrelated work.
- Use focused changes and Conventional Commit subjects when asked to commit.
- Do not commit, push, or publish unless explicitly requested.
- This repository currently has no remote. Do not create one or decide its
  owner or visibility without an explicit user decision.
