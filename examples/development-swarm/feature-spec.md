# Bounded artifact validation feature

Goal: propose a maintainable extension to the existing static artifact validators.
The source context is hash-pinned before any task executes. Planning identifies
contract changes; implementation and validation work in independent proposal
scopes; review consumes both outputs and reports unrun checks explicitly.

Acceptance criteria: malformed inputs fail closed; unsupported checks never pass;
Python source is parsed without execution; no model output is automatically applied.
The bundled offline outputs are transport/orchestration fixtures only. They are
not an implementation of a new validator or a claim of functional acceptance.
