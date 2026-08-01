# Listen Domain Glossary

This file defines shared product language. It intentionally contains no
roadmap, implementation status, or repository ownership. Product and system
boundaries live in `ECOSYSTEM.md`.

## Content Source

An external or first-party origin from which a piece of media is identified,
such as a podcast feed, a video platform, a publisher catalog, or a creator's
own collection. A source is not proof that two media files share a compatible
timeline.

## Source Identity

A stable, namespaced identifier assigned by a Content Source to a work or
item, for example a platform video ID or podcast episode GUID. It identifies
the source item, not its exact bytes or timeline compatibility.

## Content Edition

A particular editorial form of a source item: the same ordered audiovisual
content with the same timeline semantics. Trimming, replacing audio, inserting
material, or otherwise changing the timeline creates another edition.

## Media Rendition

A concrete encoding or delivery of a Content Edition, including its container,
codecs, tracks, and exact bytes. Multiple renditions can represent one edition
while having different file hashes.

## Timeline Compatibility

Evidence-backed classification of whether timed resources can be applied to a
particular Media Rendition. Exact byte identity is the strongest simple case;
matching Source Identity alone is insufficient.

## Media Offer

A lawful way to obtain or play a Media Rendition, together with availability,
integrity, and license metadata. An offer is separate from a resource package.

## Catalog Entry

The discoverable record for one Content Edition. It associates source
metadata, Media Offers, and Package Listings without combining those assets.

## Catalog Channel

A versioned, subscribable collection of Catalog Entries curated by an official
publisher or a community publisher.

## Package Listing

A mutable discovery record for a family of related Package Releases. It can
carry descriptions, ratings, moderation state, and release pointers; it is not
the installed package identity.

## Package Release

An immutable, digest-addressed publication of a `.listenpkg`, with declared
publisher, review, license, resource inventory, and compatibility evidence.
Updates create a new release rather than overwriting an existing one.

## Package Installation

The local record that a particular Package Release was accepted and its
resources were attached as candidates. Installation state is distinct from
the release and from resource activation.

## Learning Material

A local, learnable composition of media, installed resource candidates,
active resource choices, and the learner's experience state. It is not a
distributable package.

## Publisher Status

The trust classification of the publishing identity, such as official,
verified community, ordinary community, or unsigned local. Publisher Status
does not imply human review or legal clearance.

## Review Status

The declared level of content review, such as unreviewed machine output,
machine checked, sample human reviewed, or fully human reviewed. It is
independent of Publisher Status.

## License Status

The confidence and basis for media and resource usage rights, such as verified,
publisher declared, or unknown. It is independent of publisher and review
status.

## Official Starter Catalog

The permanently free, first-party curated catalog used to provide a useful
initial learning experience and reference-quality examples for the open
ecosystem. Its media must be first-party, public domain, openly licensed, or
explicitly authorized.
