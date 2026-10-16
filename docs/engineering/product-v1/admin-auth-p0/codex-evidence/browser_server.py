import sys,tempfile
from aiohttp import web
sys.path.insert(0,'/private/tmp/p0_fix/gateway/tests')
import admin_security_tests as suite
base=tempfile.mkdtemp(prefix='codex-p0-browser-')
app=suite._client(base,suite._stores(base))
web.run_app(app,host='127.0.0.1',port=18764,access_log=None)
