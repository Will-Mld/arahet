"""Sonnet F01-F10 decisions; no provider calls, private files and approved ports."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import bootstrap
import bundles
import codewalk
import consent
from tests import test_export, test_p1, test_bootstrap

HEADER='Licensed under the Apache License, Version 2.0 (the "License");'
ASF=('Licensed to the Apache Software Foundation (ASF) under one or more\n'
     'contributor license agreements. See the NOTICE file distributed with\n'
     'this work for additional information regarding copyright ownership.\n'
     'The ASF licenses this file to You under the Apache License, Version 2.0\n'
     '(the "License"); you may not use this file except in compliance with the License.')


class Licences(unittest.TestCase):
    setUp=test_export.Exports.setUp
    save_script=test_export.Exports.save_script
    export=test_export.Exports.export
    manifest=test_export.Exports.manifest

    def mit_holder(self,holder):
        return 'Copyright (c) 2024 '+holder+'\n'+bundles.MIT_BODY

    def test_f01_three_review_bypasses_and_multiline_apache_are_not_allowed(self):
        apache=(ROOT/'third_party/APACHE-2.0.txt').read_text(encoding='utf-8')
        texts=[self.mit_holder('Foo. Redistribution only to educational bodies.'),
               self.mit_holder('Bar, all commercial use needs permission slip'),
               apache.replace('Copyright [yyyy] [name of copyright owner]',
                              'Copyright 2024 Foo. Use is limited to universities.'),
               apache.replace('Copyright [yyyy] [name of copyright owner]',
                              'Copyright (c) 2024 Foo\n Not for use in military contexts.')]
        for index,text in enumerate(texts):
            with self.subTest(index=index):
                self.assertNotIn(bundles.license_id(text),bundles.ALLOWED)
                (self.project/'LICENSE').write_text(text,encoding='utf-8')
                # Even headers on all files cannot rescue a malformed copyright variable.
                (self.project/'src/main.py').write_text('# '+HEADER+'\n\n'+self.source.decode(),encoding='utf-8')
                self.raw['chapters'][0]['items'][0]['phrases'][0]['code'].update(start=3,end=4)
                self.save_script()
                result=bundles.export_bundle(self.script,self.directory/f'bad-{index}.zip',with_code=True)
                self.assertFalse(result['codeIncluded'])

    def test_f01_common_holders_symbols_maximum_and_canonical_apache_remain_allowed(self):
        for holder in ('AlpacaDB, Inc.','Microsoft Corporation','Jane Q.Public','Example Authors','A'+'a'*119):  # a name: lower-case words are refused (allow-list)
            for prefix in ('Copyright (c) 2015-2026 ','Copyright (C) 2015, 2026 ','Copyright © 2026 ','© 2026 '):
                with self.subTest(holder=holder,prefix=prefix):
                    text=prefix+holder+'\nAll rights reserved.\n'+bundles.MIT_BODY
                    self.assertEqual(bundles.license_id(text),'MIT')
        apache=(ROOT/'third_party/APACHE-2.0.txt').read_text(encoding='utf-8')
        self.assertEqual(bundles.license_id(apache),'Apache-2.0')
        self.assertEqual(bundles.license_id(apache.replace('Copyright [yyyy] [name of copyright owner]',
                              'Copyright (c) 2026 AlpacaDB, Inc.')),'Apache-2.0')

    def test_f01_holder_terms_length_sentences_and_four_credit_lines_are_refused(self):
        for word in ('only','must','may','not','shall','should','permission','permit','commercial','noncommercial',
                     'prohibited','restrict','require','educational','licence','license','except','without','terms','condition'):
            self.assertNotIn(bundles.license_id(self.mit_holder('Example '+word+' Foundation')),bundles.ALLOWED)
        for holder in ('a'*121,'Foo. Another sentence','Foo; extra','Foo\nMore words'):
            self.assertNotIn(bundles.license_id(self.mit_holder(holder)),bundles.ALLOWED)
        credits='\n'.join('Copyright (c) 2026 Author '+str(i) for i in range(4))
        self.assertNotIn(bundles.license_id(credits+'\n'+bundles.MIT_BODY),bundles.ALLOWED)
        self.assertEqual(bundles.license_id('\n'.join(credits.splitlines()[:3])+'\n'+bundles.MIT_BODY),'MIT')
        bsd=test_export.BSD_HEAD+test_export.BSD_THIRD+test_export.BSD_TAIL
        self.assertNotIn(bundles.license_id(bsd.replace('Neither the name of Example Authors','Neither the name of Example only Foundation')),bundles.ALLOWED)

    def test_f09_standard_forms_accepted_and_modified_grant_sentences_refused(self):
        for text in (HEADER, '// '+HEADER+'\ncode()', '# '+HEADER+'\n\ncode()',
                     HEADER+'\nyou may not use this file except in compliance with the License.',
                     '\n'.join('* '+line for line in ASF.splitlines())):
            with self.subTest(text=text): self.assertTrue(bundles.apache_header(text.encode()))
        for suffix in (' except for internal use',' but only for schools',' provided that permission is obtained',
                       ' (the "License"); except for copying', ' (the "License"); but only internally',
                       ' (the "License");\n# provided that you ask first', ' (the "License");\n\nexcept for resale',
                       ' (the "License"); // except for copying', ' (the "License"); /* but only internally */'):
            text='Licensed under the Apache License, Version 2.0'+suffix
            with self.subTest(text=text): self.assertFalse(bundles.apache_header(text.encode()))
        self.assertFalse(bundles.apache_header(b'Licensed to the Apache Software Foundation (ASF) under one custom restriction.'))
        self.assertFalse(bundles.apache_header(('\n'*40+HEADER).encode()))
        self.assertTrue(bundles.apache_header(('\n'*39+HEADER).encode()))

    def test_f10_refusal_manifest_names_additional_terms_and_permission_reason(self):
        apache=(ROOT/'third_party/APACHE-2.0.txt').read_text(encoding='utf-8')
        (self.project/'LICENSE').write_text(apache+'\nSubcomponents have other terms.',encoding='utf-8')
        self.export(with_code=True)
        manifest=self.manifest()
        self.assertEqual(manifest['license']['id'],'Apache-2.0 with additional terms')
        self.assertFalse(manifest['codeAllowed']); self.assertFalse(manifest['license']['codeAllowed'])
        self.assertIn('src/main.py',manifest['codeReason'])
        self.assertEqual(manifest['codeReason'],manifest['license']['reason'])
        bundles.unpack_bundle(self.output,self.cache)

    def test_f09_f10_allowed_extra_terms_rule_roundtrips_with_complete_headers(self):
        apache=(ROOT/'third_party/APACHE-2.0.txt').read_text(encoding='utf-8')
        (self.project/'LICENSE').write_text(apache+'\nSubcomponents have other terms.',encoding='utf-8')
        (self.project/'src/main.py').write_text('# '+HEADER+'\n\n'+self.source.decode(),encoding='utf-8')
        self.raw['chapters'][0]['items'][0]['phrases'][0]['code'].update(start=3,end=4)
        self.save_script()
        self.export(with_code=True)
        manifest=self.manifest()
        self.assertTrue(manifest['codeAllowed'])
        self.assertEqual(manifest['license']['rule'],'per-file-headers')
        bundles.unpack_bundle(self.output,self.cache)


class Runtime(test_p1.Base):
    def two_phrases(self,gap=0):
        self.raw['defaults']={'gapMs':gap}
        self.raw['chapters'][0]['items'][0]['phrases']=[{'id':'p1','text':'First caption'},{'id':'p2','text':'Second caption'}]
        self.save()
        return self.player()

    def test_f03_reading_time_pause_resume_and_navigation_keep_caption_position(self):
        player=self.two_phrases()
        with patch.object(codewalk.threading,'Thread'), patch.object(codewalk.time,'monotonic',return_value=0) as clock:
            player.start_phrase(0,'test')
            self.assertEqual(player.last_phrase['captionDurationSec'],3)
            self.assertIsNone(player.last_phrase['audio'])
            clock.return_value=1; player.command('pause',{},'test')
            self.assertEqual(player.caption_remaining,2)
            clock.return_value=100; player.command('play',{},'test')
            player.update_caption_clock(101)
            self.assertEqual(player.caption_remaining,1)
            with patch.object(player,'async_start',side_effect=lambda idx,source,*args:player.start_phrase(idx,source)):
                clock.return_value=101; player.command('next',{},'test')
                self.assertEqual(player.idx,1); self.assertEqual(player.caption_remaining,3)
                player.command('prev',{},'test')
                self.assertEqual(player.idx,0); self.assertEqual(player.caption_remaining,3)
            player.command('stop',{},'test')
            self.assertNotEqual(player.caption_token,player.token)

    def test_f03_real_clock_advances_only_after_reading_time_and_gap(self):
        player=self.two_phrases(150)
        with patch.object(codewalk,'tts') as tts:
            started=time.monotonic(); player.start_phrase(0,'test')
            time.sleep(.15)
            self.assertEqual(player.idx,0)
            deadline=started+5
            while player.idx==0 and time.monotonic()<deadline: time.sleep(.02)
            elapsed=time.monotonic()-started
            self.assertEqual(player.idx,1)
            self.assertGreaterEqual(elapsed,3.1)
            self.assertIsNone(player.last_phrase['audio'])
            player.command('stop',{},'test')
            tts.assert_not_called()

    def test_f03_long_caption_formula_and_pause_after_remain(self):
        self.raw['chapters'][0]['items'][0]['phrases'][0].update(text='word '*25,pauseAfter=True)
        self.save(); player=self.player()
        with patch.object(codewalk.threading,'Thread'):
            player.start_phrase(0,'test',start_at=999)
            self.assertEqual(player.last_phrase['captionDurationSec'],10)
            self.assertEqual(player.caption_remaining,10)
            player.page_event({'event':'caption-ended','kind':'phrase','token':player.token})
            self.assertEqual(player.status,'paused')

    def test_f04_availability_requires_installation_and_not_explicit_off(self):
        player=self.player()
        for installed,disabled,expected in ((None,False,False),('claude',False,True),('claude',True,False)):
            player.answerer_disabled=disabled
            with patch.object(codewalk.shutil,'which',return_value=installed):
                self.assertEqual(player.snapshot()['claudeAvailable'],expected)

    def test_f07_bad_json_is_a_json_fail_without_traceback(self):
        for text in ('{','[1,','{"chapters":'):
            self.script.write_text(text,encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(codewalk.main(['validate','--script',str(self.script)]),1)
            result=json.loads(output.getvalue())
            self.assertEqual(result['status'],'FAIL')
            self.assertEqual(result['findings'][0]['code'],'JSON')

    def test_f02_check_prints_yes_no_and_undecided_and_does_not_advertise_unapproved_answers(self):
        for value,status in ((None,'not decided'),(False,'no'),(True,'yes')):
            with patch.object(consent,'decision',return_value=value), patch.object(bootstrap,'key_state',return_value='missing'), \
                 patch.object(bootstrap,'demo_ready',return_value=False), patch.object(bootstrap,'background_player',return_value=None), \
                 patch.object(bootstrap,'which',return_value='installed'), \
                 patch.object(codewalk,'validate',return_value={'status':'PASS','phrases':1,'findings':[]}), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(bootstrap.main(['check','--quick']),0)
            lines=output.getvalue().splitlines()
            self.assertTrue(any('Azure narration and spoken questions' in line and status in line and '--azure yes|no' in line for line in lines))
            self.assertTrue(any('Claude answers' in line and status in line and '--claude yes|no' in line for line in lines))
            tool=next(line for line in lines if 'claude command-line tool' in line)
            self.assertEqual('answers page questions' in tool,value is True)


class UpgradeRun(unittest.TestCase):
    setUp=test_bootstrap.PlayerStart.setUp
    run_guide=test_bootstrap.PlayerStart.run_guide

    def test_f02_run_announces_undecided_providers_only_when_applicable(self):
        for installed in (None,'claude'):
            with patch.object(consent,'decision',return_value=None),patch.object(bootstrap,'which',return_value=installed):
                result,text=self.run_guide()
            self.assertEqual(result,0)
            self.assertEqual(text.count('Narration is off until you decide:'),1)
            self.assertEqual('Claude answers are off until you decide:' in text,bool(installed))
        with patch.object(consent,'decision',return_value=False): result,text=self.run_guide()
        self.assertNotIn('until you decide:',text)


if __name__=='__main__': unittest.main()
