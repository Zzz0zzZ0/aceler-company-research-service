"""No paid requests: exercise the real CLI seam with simulated provider replies."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from company_research_trial import anysearch_key_pool as P
from company_research_trial import company_research_trial as C
from company_research_trial.test_crm_enrichment import M, ROW, MANIFEST


def reply(code=0, stdout='Search results', stderr=''):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class KeyPoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.pool = self.root / 'keys.json'
        self.cli = self.root / 'cli.js'; self.cli.touch()
        for patcher in (patch.dict(C.os.environ, {'ANYSEARCH_KEY_POOL_FILE': str(self.pool), 'ANYSEARCH_STOP_ON_QUOTA': '1'}),
                        patch.object(C, 'ANYSEARCH_CLI', self.cli)):
            patcher.start(); self.addCleanup(patcher.stop)

    def test_persistent_exhaustion_dedup_permissions_and_explicit_reset(self):
        P.add_keys(self.pool, ['first-key-value', 'first-key-value', 'second-key-value'])
        first = P.select_key(self.pool); P.mark_exhausted(self.pool, first[0])
        P.add_keys(self.pool, ['first-key-value'])
        self.assertEqual(P.public_status(self.pool)['available'], 1)
        self.assertEqual(P.select_key(self.pool)[1], 'second-key-value')
        P.mark_exhausted(self.pool, first[0])  # delayed old request cannot exhaust new key
        self.assertEqual(P.select_key(self.pool)[1], 'second-key-value')
        P.change_key(self.pool, first[0], 'reset')
        self.assertEqual(P.public_status(self.pool)['available'], 2)
        self.assertNotIn('first-key-value', json.dumps(P.public_status(self.pool)))
        self.assertEqual(self.pool.stat().st_mode & 0o777, 0o600)
        original = self.pool.read_bytes()
        with self.assertRaises(ValueError):P.add_keys(self.pool, ['bad key'])
        self.assertEqual(self.pool.read_bytes(), original)

    def test_quota_switch_retries_same_command_and_counts_every_attempt(self):
        P.add_keys(self.pool, ['first-key-value', 'second-key-value'])
        seen=[]
        def invoke(command, **kwargs):
            key=kwargs['env']['ANYSEARCH_API_KEY'];seen.append(key)
            self.assertNotIn(key, str(command))
            return reply(1, stderr='API Error: quota exhausted') if key=='first-key-value' else reply()
        meter={'search_requests':0,'extract_requests':0,'cli_attempts':0}
        token=C.ANYSEARCH_REQUEST_METER.set(meter)
        try:
            with patch.object(C.subprocess, 'run', side_effect=invoke), patch.object(C, '_public_web_fallback') as fallback:
                self.assertEqual(C.run_anysearch_cli(['batch_search','--query','one','--query','two']), 'Search results')
                fallback.assert_not_called()
        finally:C.ANYSEARCH_REQUEST_METER.reset(token)
        self.assertEqual(seen,['first-key-value','second-key-value'])
        self.assertEqual(meter,{'search_requests':4,'extract_requests':0,'cli_attempts':2})

    def test_concurrent_old_failures_do_not_skip_usable_key(self):
        P.add_keys(self.pool, ['first-key-value', 'second-key-value'])
        barrier=threading.Barrier(5);seen=[];lock=threading.Lock()
        def invoke(command, **kwargs):
            key=kwargs['env']['ANYSEARCH_API_KEY']
            with lock:seen.append(key)
            if key=='first-key-value':
                barrier.wait(timeout=5)
                return reply(1,stderr='API Error: credits exhausted')
            return reply()
        with patch.object(C.subprocess,'run',side_effect=invoke), ThreadPoolExecutor(max_workers=5) as workers:
            results=list(workers.map(lambda _:C.run_anysearch_cli(['search','--query','example']),range(5)))
        self.assertEqual(results,['Search results']*5)
        self.assertEqual(seen.count('first-key-value'),5)
        self.assertEqual(seen.count('second-key-value'),5)
        self.assertEqual(P.public_status(self.pool)['available'],1)

    def test_all_exhausted_pauses_queue_once_without_replaying_dead_keys(self):
        P.add_keys(self.pool,['first-key-value','second-key-value'])
        with patch.object(C.subprocess,'run',return_value=reply(1,stderr='API Error: quota exhausted')) as invoke, patch.object(M,'automation_gate',return_value=None), patch.object(M,'notify_quota_pause',return_value={'status':'submitted'}) as notify:
            M.run_queue(self.root,MANIFEST,[ROW,{**ROW,'id':'second'}],1,0,True,False)
            self.assertEqual(invoke.call_count,2)
            self.assertEqual(M.read(self.root/'progress.json')['status'],'paused')
            self.assertTrue((self.root/'STOP').exists());notify.assert_called_once()
            with self.assertRaises(C.AnySearchQuotaExhausted):C.run_anysearch_cli(['search','--query','example'])
            self.assertEqual(invoke.call_count,2)

    def test_no_rotation_on_rate_limit_timeout_or_unrelated_page_text(self):
        P.add_keys(self.pool,['first-key-value','second-key-value'])
        with patch.object(C.subprocess,'run',return_value=reply(1,stderr='HTTP 429 Too many requests')) as invoke:
            with self.assertRaises(C.AnySearchPackError):C.run_anysearch_cli(['search','--query','example'])
            self.assertEqual(invoke.call_count,1)
        with patch.object(C.subprocess,'run',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):C.run_anysearch_cli(['extract','https://example.test'])
        with patch.object(C.subprocess,'run',return_value=reply(stdout='# Page about quota exhausted')):
            self.assertIn('Page about',C.run_anysearch_cli(['search','--query','example']))
        self.assertEqual(P.public_status(self.pool)['available'],2)

    def test_provider_diagnostics_redact_pooled_key(self):
        P.add_keys(self.pool,['first-key-value'])
        with patch.object(C.subprocess,'run',return_value=reply(1,stderr='bad credential first-key-value')):
            with self.assertRaises(C.AnySearchPackError) as error:C.run_anysearch_cli(['search','--query','example'])
        self.assertNotIn('first-key-value',str(error.exception))

    def test_ui_add_is_secret_safe_and_does_not_start_queue(self):
        M.save(self.root/'manifest.json',{'target':'test-db'})
        with patch.object(M,'DEFAULT_ENV_FILE',self.root/'local.env'), patch.object(M,'target',return_value='test-db'), patch.object(M,'start') as start:
            with M.key_ui_server(self.root,{}) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                origin=f'http://127.0.0.1:{server.server_port}'
                def request(path,payload,source=origin):
                    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                    connection.request('POST',path,json.dumps(payload),{'Origin':source,'Content-Type':'application/json'})
                    response=connection.getresponse();result=response.status,response.read().decode();connection.close();return result
                try:
                    self.assertEqual(request('/pool-add',{'api_keys':['first-key-value']},'https://other.test')[0],403)
                    code,body=request('/pool-add',{'api_keys':['first-key-value']})
                    self.assertEqual(code,200);self.assertNotIn('first-key-value',body);start.assert_not_called()
                    key_id=json.loads(body)['key_pool']['keys'][0]['id']
                    P.mark_exhausted(M.key_pool_file(),key_id)
                    with patch.object(M,'locked',return_value=True):
                        self.assertEqual(request('/pool-key',{'id':key_id,'action':'reset'})[0],409)
                    self.assertEqual(request('/pool-key',{'id':key_id,'action':'reset'})[0],200)
                    self.assertEqual(P.public_status(M.key_pool_file())['available'],1)
                finally:server.shutdown();thread.join()


if __name__=='__main__':unittest.main()
