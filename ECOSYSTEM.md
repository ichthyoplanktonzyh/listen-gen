# Listen Open Content Ecosystem

> Context revision: 1 — accepted by the product owner on 2026-08-01.

This is a living statement of accepted product direction and current system
boundaries. Read `CONTEXT.md` for the precise shared vocabulary. A stated
direction is not evidence that an interface already exists; the current-state
section below is explicit about what is implemented.

## Product thesis

Listen follows the useful parts of the Anki model for listening practice:

- `.listenpkg` is an open, portable learning-resource format.
- `listen-gen` is open source and lets users choose or implement providers.
- the application and Core provide a dependable package-consumption and
  long-term learning experience.
- first-party hosted convenience, discovery, synchronization, curated content,
  and optional generation can support the business without closing the format
  or forcing an official provider.
- an Official Starter Catalog should provide a permanently free, immediately
  useful cold-start experience through the same public package format.

The package is a reusable analysis artifact, not a container for the user's
entire learning world. Media, packages, and learner records remain distinct.

## System roles

### listen-app

The application owns browsing and discovery UI, media acquisition and local
state, package lookup and import orchestration, generation job UX, resource
selection UX, playback, and learning experiences. Source discovery, official
embedded playback, and lawful media acquisition are separate capabilities.

### listen-core

Core owns package validation, exact media attachment, atomic and idempotent
candidate installation, active resource selection, stable learning semantics,
and learner records. Real-time conversation and genuinely real-time or
learner-dependent model capabilities remain in Core.

### listen-gen

Gen owns expensive, reusable offline production. It accepts locally accessible
media, selects and normalizes audio, invokes replaceable provider adapters,
constructs typed resources, and emits deterministic, privacy-safe,
dependency-closed `.listenpkg` files. It provides a CLI and may later provide
a Python SDK. Provider implementations run during generation; package
consumers never execute provider code.

### Hosted Catalog/Registry (future)

A future hosted plane may own discovery metadata, Catalog Channels, Package
Listings, immutable Package Releases, publisher identities, signatures,
ratings, moderation, update notifications, and distribution. The official
service is a default convenience, not a mandatory dependency: local import and
future third-party registries remain possible, and installed learning remains
offline-capable.

## Accepted invariants

- A `.listenpkg` contains typed reusable resources, not media bytes by default.
- A package never contains learner facts, learning history, secrets, local
  filesystem paths, raw provider responses, or executable code.
- Official and community producers use the same public package contract and
  validator; official packages have no hidden format privilege.
- Users may import packages from any source. Publisher Status, Review Status,
  and License Status are separate signals and do not replace technical
  validation.
- A Package Release is immutable and digest-addressed. A Package Listing and
  human-friendly release pointer may change.
- Installing a package adds immutable resource candidates. Repeated import is
  idempotent, and installation never silently changes an existing active
  choice.
- Learner records are local user assets and are not distributed in packages.
- Media rights and resource rights are explicit and can differ. First-party
  starter media is limited to first-party, public-domain, openly licensed, or
  explicitly authorized material.
- Content identity is layered as Source Identity, Content Edition, Media
  Rendition, Timeline Compatibility, and Package Release identity. Source
  Identity alone never proves that a timed package fits a media file.
- A platform catalog adapter, playback adapter, and media acquisition adapter
  are distinct. Gen does not become a platform-policy-bypassing downloader.
- New generation capabilities migrate as coherent vertical slices. Preserve
  old behavior until fixture comparison and consumer cutover are complete;
  do not move or delete the entire legacy production tree at once.

## Current listen-gen reality

The production interface is Python 3.11+ and the CLI command
`listen-gen package from-media`. The native path currently produces only:

- `subtitle_text_track`
- `word_timeline`

It probes media, requires explicit selection when multiple audio tracks exist,
normalizes the selected track to temporary 16 kHz mono PCM audio, calls a
provider-neutral ASR adapter, fingerprints the original media bytes, and
writes the v1 package atomically. Fixture and fake-command tests exercise the
path without paid or live model calls.

The CLI also has an opt-in `listen_gen.machine-event.v1` NDJSON protocol for
App orchestration. It reports versioned lifecycle phases without speculative
percentages, returns a package digest/resource inventory/warnings on success,
uses stable redacted failure codes, and turns SIGINT/SIGTERM into a cancelled
terminal event after terminating the active media/provider process group and
cleaning temporary artifacts. The default single-JSON output remains available
for compatibility.

`listen-gen package from-lltimeline` exists only for migration compatibility;
LLTimeline is not the new production interface. The canonical v1 package
schemas remain in `listen-core/contracts/content-package/v1` and are not
copied here. `contracts.lock.json` fixes the dependency to an exact Core commit
and authoritative schema digests. V1 attachment uses the exact SHA-256 of the
original media bytes.

The following are accepted design areas but are not implemented contracts:

- Hosted Catalog/Registry APIs and storage;
- package publisher signatures and trust verification;
- Content Edition identity and cross-rendition compatibility proofs;
- an Official Starter Catalog service;
- automatic package discovery or distribution from this repository.

This local repository currently has no remote. Do not create one, choose its
owner or visibility, push it, or publish it without an explicit user decision.

## Gen responsibilities

- keep provider and model implementations replaceable behind normalized seams;
- generate expensive offline resources and their truthful provenance;
- produce deterministic, allowlisted, dependency-closed packages;
- retain original-media identity across temporary preprocessing;
- reject ambiguous media inputs rather than guessing an audio track;
- keep routine and CI tests deterministic and free of paid/live calls;
- verify output against the Core-owned contract when a Core checkout is
  available;
- migrate each later resource family only after semantic comparison with the
  old path.

## Gen non-responsibilities

- defining the canonical content-package schema;
- Catalog or Registry search, ranking, ratings, moderation, distribution, or
  publisher trust policy;
- deciding media copyright or platform download policy;
- installing packages, persisting candidates, or selecting active resources;
- learner records, review schedules, learner profiles, playback, or learning
  UI;
- real-time conversation, recording feedback, or learner-dependent inference;
- embedding or executing provider plugins inside packages;
- silently copying, deleting, or owning Core's complete legacy production
  pipeline;
- creating or publishing this repository's remote.

## Migration order

For each offline generation slice:

1. define and validate the package resource semantics;
2. implement native generation behind a replaceable provider seam;
3. compare old and new paths with fixed, no-paid fixtures;
4. add candidate-only Core import and consumer support;
5. cut application traffic to the package path;
6. observe compatibility and rollback behavior;
7. only then deprecate and remove the corresponding legacy producer.

This ordering does not authorize deletion of Core capabilities that are still
used by the application or that also serve real-time and learner-dependent
workflows.
