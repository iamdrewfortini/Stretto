# SPDX-License-Identifier: Apache-2.0
"""Synthetic-only consent, privacy and full-event integrity regressions."""
import unittest

from perception.capture import Event, EventStore, Source, ingest, AdaptiveSampler
from perception.consent import ConsentRegistry


class PerceptionFailureRegressions(unittest.TestCase):
    def setUp(self):
        self.registry = ConsentRegistry(); self.registry.grant('p', ['screen'], ['assist'], 100, 0)
        self.store = EventStore()

    def ingest(self, describe, **kwargs):
        return ingest(self.registry, self.store, 'p', b'synthetic-fixture-key', 'screen', 'assist',
                      b'SYNTHETIC_NOT_MEDIA', describe, 1, **kwargs)

    def test_revocation_and_regrant_during_describe_cannot_commit(self):
        for regrant in (False, True):
            self.setUp()
            def describe(raw):
                self.registry.revoke('p', 2)
                if regrant: self.registry.grant('p', ['screen'], ['assist'], 100, 2)
                return {'text': 'synthetic description'}
            with self.subTest(regrant=regrant): self.assertIsNone(self.ingest(describe, now_fn=lambda:3))
            self.assertEqual(self.store.events, [])

    def test_expiry_while_describe_runs_cannot_commit(self):
        result=self.ingest(lambda raw:{'text':'synthetic description'},now_fn=lambda:101)
        self.assertIsNone(result);self.assertEqual(self.store.events,[])

    def test_source_rechecks_revoke_regrant_and_expiry_after_reader(self):
        for kind in ('revoke','regrant','expire'):
            self.setUp();clock=[1]
            def reader():
                if kind!='expire': self.registry.revoke('p',2)
                if kind=='regrant': self.registry.grant('p',['screen'],['assist'],100,2)
                clock[0]=101 if kind=='expire' else 3
                return b'SYNTHETIC_NOT_MEDIA'
            with self.subTest(kind=kind): self.assertEqual(list(Source('screen',reader).items(self.registry,'p','assist',lambda:clock[0])),[])

    def test_ttl_and_times_refuse_nonfinite_bool_negative_and_pregrant(self):
        for value in (float('inf'),float('nan'),-float('inf'),True,0,-1):
            with self.subTest(ttl=value),self.assertRaises(ValueError):self.registry.grant('p',['screen'],['assist'],value,0)
        for value in (float('inf'),float('nan'),True,-1):
            with self.subTest(now=value),self.assertRaises(ValueError):self.registry.grant('p',['screen'],['assist'],1,value)
            self.assertFalse(self.registry.allows('p','screen','assist',value))
        self.registry.grant('p',['screen'],['assist'],10,10)
        self.assertFalse(self.registry.allows('p','screen','assist',9))
        self.assertTrue(self.registry.allows('p','screen','assist',10))

    def test_description_rejects_raw_extra_and_nontext_activity(self):
        for description in ({'text':'fixture','pixels':'SYNTHETIC'}, {'text':'fixture','activity':b'SYNTHETIC'},
                            {'text':b'SYNTHETIC'}, {'text':'data:image/png;base64,SYNTHETIC'}):
            with self.subTest(description=description),self.assertRaises(ValueError):self.ingest(lambda raw:description)
        self.assertEqual(self.store.events,[])

    def test_activity_and_app_are_redacted_too(self):
        event=self.ingest(lambda raw:{'text':'fixture','activity':'email fixture@example.com'},app='fixture@example.com')
        self.assertNotIn('@',event['activity']);self.assertNotIn('@',event['app'])
        self.assertEqual(event['redactions']['EMAIL'],2);self.assertTrue(self.store.verify())

    def test_event_and_store_validate_before_any_append(self):
        for value in ({'id':'bad'}, Event):
            with self.subTest(value=value),self.assertRaises(ValueError):self.store.add(value)
        self.assertEqual(self.store.events,[]);self.assertEqual(self.store.chain.rows,[])
        event=self.ingest(lambda raw:{'text':'fixture'})
        with self.assertRaises(TypeError):event['text']='changed'
        with self.assertRaises(ValueError):Event({**event,'pixels':'SYNTHETIC'})
        with self.assertRaises(ValueError):Event({**event,'activity':b'SYNTHETIC'})

    def test_stored_snapshots_do_not_alias_returned_nested_fields(self):
        event=self.ingest(lambda raw:{'text':'fixture@example.com'})
        event['redactions']['EMAIL']=999
        view=self.store.events;view[0]['text']='changed';view.clear()
        self.assertEqual(self.store.events[0]['redactions']['EMAIL'],1)
        self.assertNotEqual(self.store.events[0]['text'],'changed');self.assertTrue(self.store.verify())

    def test_full_event_tampering_and_missing_payload_fail_verification(self):
        for key,value in [('text','changed'),('app','changed'),('duration_s',999),('duration_s',True),('redactions',{'EMAIL':999})]:
            self.setUp();self.ingest(lambda raw:{'text':'fixture'})
            self.store._events[0][key]=value
            with self.subTest(key=key,value=value):self.assertFalse(self.store.chain.verify())
        self.setUp();self.ingest(lambda raw:{'text':'fixture'})
        self.store.chain.rows.clear();self.assertFalse(self.store.verify())

    def test_invalid_sampler_config_and_time_fail_closed(self):
        for args in [(10,1,.2),(0,1,.2),(1,float('inf'),.2),(1,2,float('nan'))]:
            with self.subTest(args=args),self.assertRaises(ValueError):AdaptiveSampler(*args)
        sampler=AdaptiveSampler();sampler.should_capture(1,.5)
        for now,change in [(0,.5),(float('nan'),.5),(2,float('inf'))]:
            with self.subTest(now=now,change=change),self.assertRaises(ValueError):sampler.should_capture(now,change)

    def test_consent_history_suffix_deletion_is_detected(self):
        self.registry.revoke('p',2)
        self.registry.chain.rows.pop()
        self.assertFalse(self.registry.chain.verify())
        with self.assertRaises(ValueError):self.registry.grant('p',['screen'],['assist'],10,3)


if __name__=='__main__':unittest.main()
