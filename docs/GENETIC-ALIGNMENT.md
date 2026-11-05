# Canonical symbolic communication alignment

Derived from Drew's request for all agent, pipeline, multimodal, cross-host and edge communication to align with the existing symbolic gene contract.

The authority is `daclab/meta-agent-pipeline`, `src/meta_pipeline/protocol.py`, versioned as `diatonic-13-v1`. Its STAM opcode profile is 78 bits stored in ten bytes with two zero high padding bits. A 72-bit alternative is not established by the inspected authority. The opcode profile does not contain all arguments, identity, consent, policy, payload or execution evidence; those retain their separate boundaries.

`cells/data/communication-contract.json` is a generated, pinned export from the canonical source commit, not a new definition. `cells.communication` rejects source-artifact or contract-digest drift. Existing development events now carry `_communication` envelopes matching the canonical SDK EventEnvelope fields. They bind the original payload digest, coordinator-local tick and previous event hash. Reports include the protocol and contract digest.

Local tests reject foreign versions, width aliases, tampered payloads, reordered/replayed local ticks, invalid tracks and statuses, extra fields and corrupted source exports. Opaque evidence references for text, image, audio, video, binary and mixed modalities survive the envelope unchanged. The canonical SDK schema independently accepted actual development event envelopes.

This establishes local event-envelope conformance, not full payload or sensor correctness. Local hashes and ticks do not authenticate remote hosts, provide distributed consensus or prove external causal order. Existing agent policy, user consent, downstream authority and product verification still apply. There is no model call, deployment, host change or permission grant in this adapter.

Remaining alignment work: Handoff's live/recorded multimodal bus needs an explicit exchange-boundary adapter; live host and edge consumers need protocol/version and authenticated-transport proofs; installed artifacts and production services remain separate from local source/test evidence. The new package-data declaration is checked in source; an installed-wheel proof belongs in the existing CI build path.
