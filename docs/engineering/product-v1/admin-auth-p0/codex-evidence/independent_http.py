import sys,asyncio,tempfile,importlib.util,json,logging
from pathlib import Path
sys.path.insert(0,'/private/tmp/p0_fix/gateway/tests')
import admin_security_tests as suite
from aiohttp.test_utils import TestClient,TestServer
ROOT=Path('/private/tmp/codex-xiaozhi-admin-p0-audit')
results=[]
def check(name,cond,detail=None):
 results.append({'name':name,'pass':bool(cond),'detail':detail}); print(('PASS ' if cond else 'FAIL ')+name+' '+json.dumps(detail,ensure_ascii=False))
def load(rev):
 spec=importlib.util.spec_from_file_location('audit_auth_'+rev,ROOT/rev/'gateway/app/admin/auth.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
async def run(rev):
 mod=load(rev); tmp=tempfile.mkdtemp(prefix='codex-p0-http-'); cfg=suite._cfg(tmp); app=suite._client(tmp,suite._stores(tmp)); store=mod.TokenStore(cfg.token_file,cfg.token_env);store.reload();app['admin_token_store']=store
 statuses={}
 async with TestClient(TestServer(app)) as c:
  for name,header in [('valid','Bearer '+suite.FIX_TOKEN),('missing',None),('empty','Bearer '),('ascii_wrong','Bearer temporary-wrong'),('nonascii','Bearer 中文－temporary'),('bom','Bearer \ufefftemporary'),('latin1','Bearer étemporary'),('whitespace_tail','Bearer '+suite.FIX_TOKEN+'\u3000'),('wrong_scheme','Basic temporary'),('length_8000','Bearer '+'x'*8000)]:
   r=await c.get('/admin/health',headers={'Authorization':header} if header is not None else {});body=await r.text();statuses[name]=r.status
   expected=200 if name in ['valid','whitespace_tail'] else (500 if rev=='baseline' and name in ['nonascii','bom','latin1'] else 401)
   check(rev+' HTTP '+name,r.status==expected,{'status':r.status,'expected':expected})
   if r.status==401:check(rev+' uniform body '+name,json.loads(body)['error']=='unauthorized' and set(json.loads(body))=={'error','request_id'})
   check(rev+' no test token in body '+name,suite.FIX_TOKEN not in body)
  r=await c.get('/shared.js');check(rev+' /shared.js available',r.status==200,{'status':r.status})
 for name,value in [('none',None),('empty',''),('bytes',b'temporary'),('int',123),('bool',True),('surrogate','\ud800'),('unicode','中文'),('long','x'*100000)]:
  try: outcome=store.matches(value); exception=None
  except Exception as e: outcome=None;exception=type(e).__name__
  expected_exception=rev=='baseline' and name in ['bytes','int','bool','surrogate','unicode']
  check(rev+' matches '+name,(exception=='TypeError') if expected_exception else (exception is None and outcome is False),{'return':outcome,'exception':exception})
 return statuses
async def main():
 before=await run('baseline');after=await run('final');check('before/after Unicode HTTP 500→401',before['nonascii']==500 and after['nonascii']==401)
 (ROOT/'independent_http.json').write_text(json.dumps({'results':results,'before':before,'after':after},ensure_ascii=False,indent=2))
 print('TOTAL',len(results),'PASS',sum(x['pass'] for x in results),'FAIL',sum(not x['pass'] for x in results))
asyncio.run(main())
