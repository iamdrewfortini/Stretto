# SPDX-License-Identifier: Apache-2.0
"""Source-pinned canonical SDK event adapter; hashes prove consistency, not identity."""
import hashlib
from importlib.resources import files
import json
import re

PROTOCOL_ID = 'diatonic-13-v1'
CONTRACT_SHA256 = 'b42f4a5214f9c58b38e7d37fb4cd90268a580ab9d51c3afd651172ebee74e036'
SOURCE_ARTIFACT_SHA256 = '8b4fca3e43932aa74fd2b871dd3ab3bcccdfc55e453af9a51a0f1f814ce373b1'
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def contract_document():
    raw = files('cells').joinpath('data/communication-contract.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_ARTIFACT_SHA256:
        raise ValueError('canonical communication source artifact drift')
    artifact = json.loads(raw)
    doc = artifact['contract']
    if (artifact.get('contract_sha256') != CONTRACT_SHA256
            or hashlib.sha256(canonical(doc)).hexdigest() != CONTRACT_SHA256
            or doc.get('id') != PROTOCOL_ID):
        raise ValueError('canonical communication contract drift')
    return doc


def event_envelope(payload, *, track, tick, previous, status):
    contract_document()
    if type(track) is not int or not 1 <= track <= 13 or type(tick) is not int or tick < 1:
        raise ValueError('invalid communication track/tick')
    if not isinstance(previous, str) or not _SHA.fullmatch(previous) or status not in ('observed', 'unresolved'):
        raise ValueError('invalid communication chain/status')
    return dict(protocol=PROTOCOL_ID, track=track, tick=tick, previous_event_hash=previous,
                payload_sha256=hashlib.sha256(canonical(payload)).hexdigest(),
                contract_sha256=CONTRACT_SHA256, status=status)


def verify_event(payload, envelope, *, previous, tick):
    if not isinstance(envelope, dict) or set(envelope) != {
            'protocol', 'track', 'tick', 'previous_event_hash', 'payload_sha256',
            'contract_sha256', 'status'}:
        raise ValueError('invalid communication envelope fields')
    if (type(envelope['track']) is not int or type(envelope['tick']) is not int
            or any(type(envelope[name]) is not str for name in (
                'protocol', 'previous_event_hash', 'payload_sha256', 'contract_sha256', 'status'))):
        raise ValueError('communication envelope scalar types must match the canonical schema')
    expected = event_envelope(payload, track=envelope['track'], tick=tick,
                              previous=previous, status=envelope['status'])
    if envelope != expected:
        raise ValueError('foreign, stale, tampered or reordered communication envelope')
    return True
