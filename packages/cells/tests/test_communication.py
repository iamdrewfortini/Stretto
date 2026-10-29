# SPDX-License-Identifier: Apache-2.0
import copy
import hashlib
import unittest
from unittest.mock import patch

from cells.communication import (CONTRACT_SHA256, PROTOCOL_ID, canonical,
                                 contract_document, event_envelope, verify_event)
from cells.development import DevelopmentTask, ExecutionPolicy, DevelopmentSwarm, offline_dry_run


class Communication(unittest.TestCase):
    def test_profile_is_78_opcode_bits_not_full_wire_frame(self):
        doc = contract_document()
        self.assertEqual(doc['opcode_bits'], 13 * 3 * 2)
        self.assertEqual(doc['opcode_storage_bytes'], 10)
        self.assertEqual(len(doc['channels']), 13)
        self.assertFalse(doc['encoding_is_proof'])
        self.assertEqual(hashlib.sha256(canonical(doc)).hexdigest(), CONTRACT_SHA256)

    def test_envelopes_preserve_all_payload_modalities_without_interpretation(self):
        for modality in ('text', 'image', 'audio', 'video', 'binary', 'mixed'):
            payload = {'modality': modality, 'evidence_ref': 'opaque-source', 'unknown': None}
            env = event_envelope(payload, track=10, tick=1, previous='0'*64, status='observed')
            self.assertTrue(verify_event(payload, env, previous='0'*64, tick=1))
            self.assertEqual(env['protocol'], PROTOCOL_ID)
            changed = dict(payload, unknown='invented')
            with self.assertRaises(ValueError): verify_event(changed, env, previous='0'*64, tick=1)

    def test_foreign_width_contract_tamper_sequence_and_unknown_fields_refused(self):
        payload = {'event': 'fixture'}
        good = event_envelope(payload, track=11, tick=2, previous='1'*64, status='unresolved')
        for field, value in [('protocol','72-bit'), ('contract_sha256','f'*64), ('tick',1),
                             ('previous_event_hash','0'*64), ('payload_sha256','0'*64),
                             ('track',14), ('status','VERIFIED'), ('extra',True)]:
            bad = dict(good); bad[field] = value
            with self.assertRaises(ValueError): verify_event(payload,bad,previous='1'*64,tick=2)
        for tick in (True, 0, -1):
            with self.assertRaises(ValueError): event_envelope(payload,track=10,tick=tick,previous='0'*64,status='observed')

    def test_source_export_corruption_refused(self):
        with patch('cells.communication.files') as mocked:
            mocked.return_value.joinpath.return_value.read_bytes.return_value = b'{}'
            with self.assertRaises(ValueError): contract_document()

    def test_actual_development_events_bind_payload_and_prior_chain(self):
        policy = ExecutionPolicy(rubric_sha256='a'*64)
        task = DevelopmentTask('fixture','Offline fixture',('a.txt',),'a'*64)
        report = DevelopmentSwarm([task],policy).execute(offline_dry_run,lambda task,out:True)
        self.assertEqual(report['communication_contract_sha256'],CONTRACT_SHA256)
        previous='0'*64
        for index,event in enumerate(report['events']):
            payload=copy.deepcopy(event); env=payload.pop('_communication'); digest=payload.pop('sha256')
            self.assertTrue(verify_event(payload,env,previous=previous,tick=index+1))
            full=dict(payload,_communication=env)
            self.assertEqual(hashlib.sha256(canonical(full)).hexdigest(),digest)
            previous=digest
