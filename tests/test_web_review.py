from __future__ import annotations
import argparse
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skill/scripts'))
import subtitle_focus as focus
import subtitle_review as review


class WebReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.srt=self.root/'input.srt'
        self.srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好🙂 Model Y 0.8元\n\n2\n00:00:01,000 --> 00:00:02,000\n重复重复重复\n',encoding='utf-8')
        self.lock=self.root/'lock.json';self.plan=self.root/'plan.json'
        with contextlib.redirect_stdout(io.StringIO()):
            focus.command_lock(argparse.Namespace(srt=str(self.srt),output=str(self.lock),confirmed=False,test_only=True))
            focus.command_plan(argparse.Namespace(srt=str(self.srt),lock=str(self.lock),output=str(self.plan),max_chars=40))
        self.session=review.ReviewSession(focus,self.plan,self.root/'review',title='测试',test_mode=True)

    def tearDown(self):self.temp.cleanup()
    def payload(self):
        s=self.session
        return {'session_id':s.state['session_id'],'source_sha256':s.plan['source_sha256'],'plan_sha256':s.config['plan_sha256'],
                'revision':s.state['revision'],'segments':copy.deepcopy(s.state['selection'])}
    def confirm(self,rows=None,request='test-request-000001'):
        p=self.payload();p.update(confirmed=True,request_id=request)
        if rows is not None:p['segments']=rows
        return self.session.confirm(p)

    def test_confirmation_archives_exact_unicode_ranges_and_srt(self):
        p=self.payload();p['segments'][0]['ranges']=[[2,3],[4,11]];p['segments'][1]['ranges']=[[2,4]]
        r=self.confirm(p['segments']);base=self.root/'review'/r['version']
        plan=review.read(base/'caption-plan.json');focus.verify_plan_source(plan)
        self.assertEqual(plan['segments'][0]['highlights'][0]['text'],'🙂')
        self.assertEqual(plan['segments'][1]['highlights'][0]['start'],2)
        self.assertEqual((base/'字幕原文.srt').read_bytes(),self.srt.read_bytes())
        text=(base/'字幕高亮确认记录.md').read_text()
        self.assertIn('background-color:#FFD600',text);self.assertIn('00:00:01,000',text)
        self.assertIn('未登记使用',text);self.assertTrue(r['test_only'])
        self.assertEqual(set(r['files']),{'字幕原文.srt','highlights.json','caption-plan.json','字幕高亮确认记录.md'})

    def test_plain_choices_are_explicit_and_pass_cadence(self):
        r=self.confirm();p=review.read(self.root/'review'/r['version']/'caption-plan.json')
        self.assertEqual(len(p['plain_overrides']),2)
        self.assertEqual(focus.validate_highlight_policy(p)[0],[])

    def test_draft_is_not_confirmation_and_survives_restart(self):
        p=self.payload();p['segments'][0]['ranges']=[[0,2]]
        self.session.draft(p)
        s=review.ReviewSession(focus,self.plan,self.root/'review',title='测试',test_mode=True)
        self.assertEqual(s.state['revision'],1);self.assertEqual(s.state['status'],'draft')
        self.assertFalse(list((self.root/'review').glob('v*')))

    def test_double_submission_is_idempotent(self):
        p=self.payload();p.update(confirmed=True,request_id='test-request-000001')
        a=self.session.confirm(p);b=self.session.confirm(p)
        self.assertEqual(a,b);self.assertEqual(len(list((self.root/'review').glob('v*'))),1)
        p['segments'][0]['ranges']=[[0,2]]
        with self.assertRaisesRegex(review.ReviewError,'同一提交'):self.session.confirm(p)

    def test_stale_tab_does_not_overwrite(self):
        stale=self.payload();p=self.payload();p['segments'][0]['ranges']=[[0,2]];self.session.draft(p)
        with self.assertRaisesRegex(review.ReviewError,'另一个页面'):self.session.draft(stale)
        self.assertEqual(self.session.state['selection'],p['segments'])

    def test_edit_invalidates_receipt_and_new_confirmation_preserves_history(self):
        first=self.confirm();path=self.root/'review'/first['version']/'caption-plan.json'
        p=self.payload();p['segments'][0]['ranges']=[[0,2]];self.session.draft(p)
        with self.assertRaisesRegex(focus.FocusError,'失效'):focus.verify_plan_source(review.read(path))
        second=self.confirm(request='test-request-000002');self.assertEqual(second['version'],'v002')
        self.assertTrue(path.exists());focus.verify_plan_source(review.read(self.root/'review/v002/caption-plan.json'))

    def test_corrupted_plan_and_archive_cannot_render(self):
        r=self.confirm();path=self.root/'review'/r['version'];p=review.read(path/'caption-plan.json')
        p['segments'][0]['highlights']=[{'start':0,'end':2,'text':'你好'}]
        with self.assertRaisesRegex(focus.FocusError,'已被修改'):focus.verify_plan_source(p)
        (path/'字幕高亮确认记录.md').write_text('modified')
        with self.assertRaisesRegex(focus.FocusError,'归档文件'):focus.verify_plan_source(review.read(path/'caption-plan.json'))

    def test_source_change_rejected(self):
        self.srt.write_text(self.srt.read_text()+'\n')
        with self.assertRaisesRegex(review.ReviewError,'changed'):self.confirm()
        self.assertEqual(self.session.state['status'],'draft')

    def test_plan_change_rejected(self):
        p=review.read(self.plan);p['segments'][0]['end_ms']=900;review.atomic_json(self.plan,p)
        with self.assertRaisesRegex(review.ReviewError,'源方案'):self.confirm()

    def test_mismatches_and_invalid_ranges_rejected(self):
        for change in [lambda p:p.update(source_sha256='wrong'),lambda p:p.update(plan_sha256='wrong'),
                       lambda p:p['segments'][0].update(id='unknown'),lambda p:p['segments'][0].update(text='伪造')]:
            p=self.payload();change(p)
            with self.assertRaises(review.ReviewError):self.session.draft(p)
        for spans in [[[0,999]],[[-1,1]],[[1,1]],[[True,2]],[[0,3],[2,4]],[[4,5],[0,1]],['bad']]:
            p=self.payload();p['segments'][0]['ranges']=spans
            with self.assertRaises(review.ReviewError):self.session.draft(p)
        self.assertEqual(self.session.state['revision'],0)

    def test_missing_user_confirmation_rejected(self):
        p=self.payload();p['request_id']='test-request-000001'
        with self.assertRaisesRegex(review.ReviewError,'明确点击'):self.session.confirm(p)

    def test_archive_failure_never_acknowledges_confirmation(self):
        real=Path.write_text
        def fail(path,*a,**kw):
            if path.name=='字幕高亮确认记录.md':raise OSError('disk full')
            return real(path,*a,**kw)
        with patch.object(Path,'write_text',fail):
            with self.assertRaises(OSError):self.confirm()
        self.assertEqual(self.session.state['status'],'draft');self.assertFalse(list((self.root/'review').glob('v*')))
        self.assertFalse(list((self.root/'review').glob('.pending-*')))

    def test_lost_pointer_write_can_recover_identical_confirmation(self):
        real=review.atomic_json
        def fail(path,value):
            if Path(path)==self.session.state_path:raise OSError('simulated crash')
            return real(path,value)
        with patch.object(review,'atomic_json',fail):
            with self.assertRaises(OSError):self.confirm()
        self.assertEqual(self.session.state['status'],'draft')
        self.session=review.ReviewSession(focus,self.plan,self.root/'review',title='测试',test_mode=True)
        r=self.confirm();self.assertEqual(r['version'],'v001');self.assertEqual(self.session.state['status'],'confirmed')

    def test_existing_directory_cannot_be_rebound(self):
        with self.assertRaisesRegex(review.ReviewError,'绑定其他'):
            review.ReviewSession(focus,self.plan,self.root/'review',title='other',test_mode=True)

    def test_test_lock_is_not_human_approval(self):
        lock=review.read(self.lock);plan=review.read(self.plan)
        self.assertFalse(lock['confirmed']);self.assertTrue(lock['test_only']);self.assertFalse(plan['source_lock']['confirmed'])
        with self.assertRaisesRegex(review.ReviewError,'测试字幕'):
            review.ReviewSession(focus,self.plan,self.root/'production')

    def test_markdown_escapes_html_in_source(self):
        rows=self.payload()['segments'];rows[0]['text']='<script>alert(1)</script>';rows[0]['ranges']=[[0,8]]
        text=self.session.markdown(rows,'v001',review.now())
        # The source of truth is the immutable segment, not submitted alternate text.
        self.assertNotIn('<script>',text)

    def test_test_fixture_cannot_register_production_delivery(self):
        r=self.confirm()
        with self.assertRaisesRegex(focus.FocusError, "Test-only"):
            focus.command_deliver(argparse.Namespace(video=str(self.root/'video.mp4'),srt=str(self.srt),
                plan=str(self.root/'review'/r['version']/'caption-plan.json'),style=str(focus.SKILL_ROOT/'assets/default-style.json')))

    def test_test_fixture_cannot_render_without_explicit_short_duration(self):
        r=self.confirm();video=self.root/'video.mp4';video.touch()
        with patch.object(focus,'probe_video',return_value={'duration':2,'width':640,'height':360}):
            for duration in [None,31,0,-1]:
                with self.assertRaisesRegex(focus.FocusError,'Test-only'):
                    focus.command_render(argparse.Namespace(video=str(video),output=str(self.root/'out.mp4'),
                        plan=str(self.root/'review'/r['version']/'caption-plan.json'),
                        style=str(focus.SKILL_ROOT/'assets/default-style.json'),tolerance_ms=100,duration=duration))

    def test_receipt_must_retain_confirmation_and_session_identity(self):
        r=self.confirm();dest=self.root/'review'/r['version'];p=review.read(dest/'caption-plan.json')
        r['confirmed']=False;review.atomic_json(dest/'receipt.json',r)
        with self.assertRaisesRegex(focus.FocusError,'确认凭据'):focus.verify_plan_source(p)

    def test_confirmation_source_cannot_change_during_bundle_write(self):
        real=self.session.markdown
        def mutate(*args):
            result=real(*args);self.srt.write_text(self.srt.read_text()+'\n');return result
        with patch.object(self.session,'markdown',mutate):
            with self.assertRaisesRegex(review.ReviewError,'changed'):self.confirm()
        self.assertEqual(self.session.state['status'],'draft')
        self.assertFalse(list((self.root/'review').glob('v*')))

    def test_http_auth_origin_host_and_payload_limits(self):
        server=review.make_server(self.session);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None,headers=None):
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                 headers=headers or {})
            try:
                with urllib.request.urlopen(req,timeout=2) as r:return r.status,r.read()
            except urllib.error.HTTPError as e:return e.code,e.read()
        try:
            self.assertEqual(request('/api/session')[0],403)
            self.assertEqual(request('/api/session',headers={'X-Review-Token':self.session.token})[0],200)
            h={'X-Review-Token':self.session.token,'Content-Type':'application/json'}
            self.assertEqual(request('/api/draft',self.payload(),h)[0],403)
            h['Origin']='https://evil.example';self.assertEqual(request('/api/draft',self.payload(),h)[0],403)
            h['Origin']=base;self.assertEqual(request('/api/draft',self.payload(),h)[0],200)
            self.assertEqual(request('/../../etc/passwd',headers=h)[0],404)
            self.assertEqual(request('/api/session',headers={**h,'Host':'evil.example'})[0],403)
            self.assertEqual(request('/api/draft',[],h)[0],400)
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            conn.putrequest('POST','/api/draft')
            for key,value in h.items():conn.putheader(key,value)
            conn.putheader('Content-Length','2000001');conn.endheaders()
            response=conn.getresponse();self.assertEqual(response.status,413);response.read();conn.close()
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
