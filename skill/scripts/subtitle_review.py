"""Local, versioned subtitle review. No cloud, arbitrary file API or shell commands."""
from __future__ import annotations
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with tmp.open('x', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class ReviewError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message); self.status = status


def plan_digest(plan):
    p = copy.deepcopy(plan)
    p.pop('review_confirmation', None)
    return digest(p)


def verify_confirmation(plan):
    """Review metadata is a workflow receipt, not proof against a malicious local user."""
    info = plan.get('review_confirmation')
    if not info:
        return
    receipt = read(info['receipt'])
    if receipt.get('plan_sha256') != plan_digest(plan):
        raise ReviewError('确认后的高亮方案已被修改，请重新审核')
    state = read(info['state'])
    if (receipt.get('kind') != 'subtitle-focus-review-receipt' or receipt.get('confirmed') is not True
            or receipt.get('session_id') != state.get('session_id')
            or receipt.get('source_sha256') != plan.get('source_sha256')):
        raise ReviewError('确认凭据与当前会话不匹配')
    if state.get('status') != 'confirmed' or state.get('active_version') != receipt['version']:
        raise ReviewError('该确认已失效或已有新版本，请重新确认')
    version = Path(info['receipt']).parent
    for name, expected in receipt['files'].items():
        p = version / name
        if p.parent != version or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ReviewError('归档文件不完整或已改动：' + name)


class ReviewSession:
    def __init__(self, focus, plan_path, output, title='字幕高亮审核', terms=None,
                 video=None, style=None, sample_seconds=12, test_mode=False):
        self.focus = focus
        self.plan_path = Path(plan_path).resolve()
        self.plan = read(self.plan_path)
        focus.verify_plan_source(self.plan)
        errors = focus.validate_plan(self.plan)
        if errors: raise ReviewError('; '.join(errors))
        self.plan.pop('review_confirmation', None)
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output / 'session.json'
        self.lock = threading.RLock()
        self.worker = None
        self.token = secrets.token_urlsafe(32)
        self.video = Path(video).resolve() if video else None
        self.style = Path(style).resolve() if style else focus.SKILL_ROOT / 'assets/default-style.json'
        self.sample_seconds = float(sample_seconds)
        if not 1 <= self.sample_seconds <= 30: raise ReviewError('样片时长必须为 1–30 秒')
        self.test_mode = bool(test_mode)
        if self.plan.get('source_lock', {}).get('test_only') and not self.test_mode:
            raise ReviewError('测试字幕只能用于 --test-mode 验收')
        if self.video:
            focus.probe_video(self.video)
            focus.validate_style(read(self.style))
        config = {'plan_sha256': digest(self.plan), 'title': title, 'terms': terms or [],
                  'video': str(self.video) if self.video else None,
                  'video_sha256': focus.sha256_file(self.video) if self.video else None,
                  'style_sha256': focus.sha256_file(self.style),
                  'sample_seconds': self.sample_seconds, 'test_mode': self.test_mode}
        self.config = config
        if self.state_path.exists():
            state = read(self.state_path)
            if state['config'] != config: raise ReviewError('审核目录已绑定其他字幕或配置，请使用新目录')
        else:
            state = {'kind': 'subtitle-focus-web-session', 'version': 1, 'session_id': uuid.uuid4().hex,
                     'config': config, 'revision': 0, 'status': 'draft', 'active_version': None,
                     'selection': self.initial_selection(), 'created_at': now(), 'updated_at': now()}
            atomic_json(self.state_path, state)
        self.state = state
        # A committed directory survives a lost response or process exit. It is never
        # silently activated; retrying the identical confirmation repairs its pointer.

    def initial_selection(self):
        return [{'id': s['id'], 'text': s['text'], 'ranges': [[h['start'], h['end']] for h in s.get('highlights', [])]}
                for s in self.plan['segments']]

    def check_source(self):
        if digest(read(self.plan_path)) != self.config['plan_sha256']:
            raise ReviewError('源方案已变化，请重新生成审核页', 409)
        try: self.focus.verify_plan_source(self.plan)
        except self.focus.FocusError as e: raise ReviewError(str(e), 409)

    def selection(self, payload):
        if payload.get('session_id') != self.state['session_id'] or payload.get('source_sha256') != self.plan['source_sha256'] or payload.get('plan_sha256') != self.config['plan_sha256']:
            raise ReviewError('审核会话、源字幕或分段版本不匹配', 409)
        rows = payload.get('segments')
        if not isinstance(rows, list) or len(rows) != len(self.plan['segments']): raise ReviewError('字幕数量不匹配')
        result = []
        for row, source in zip(rows, self.plan['segments']):
            if not isinstance(row, dict) or row.get('id') != source['id'] or row.get('text') != source['text']:
                raise ReviewError('字幕 ID 或逐字文本不匹配')
            ranges = row.get('ranges')
            if not isinstance(ranges, list): raise ReviewError('范围必须为数组')
            previous = 0
            for pair in ranges:
                if not isinstance(pair, list) or len(pair) != 2 or any(type(n) is not int for n in pair): raise ReviewError('无效的逐字范围')
                a,b = pair
                if a < previous or b <= a or b > len(source['text']): raise ReviewError('范围越界、乱序或重叠')
                previous = b
            result.append({'id': source['id'], 'text': source['text'], 'ranges': copy.deepcopy(ranges)})
        return result

    def save_state(self, state):
        atomic_json(self.state_path, state)
        self.state = state

    def public(self):
        with self.lock:
            return {'session_id': self.state['session_id'], 'title': self.config['title'],
                    'source_sha256': self.plan['source_sha256'], 'plan_sha256': self.config['plan_sha256'],
                    'revision': self.state['revision'], 'status': self.state['status'],
                    'active_version': self.state['active_version'], 'test_mode': self.test_mode,
                    'segments': self.plan['segments'], 'selection': self.state['selection'],
                    'terms': self.config['terms'], 'video': bool(self.video), 'sample': self.sample_status(),
                    'archive_directory': str(self.output)}

    def sample_status(self):
        v = self.state.get('active_version')
        p = self.output / v / 'sample-status.json' if v else None
        return read(p) if p and p.exists() else None

    def check_revision(self, payload):
        if type(payload.get('revision')) is not int or payload['revision'] != self.state['revision']:
            raise ReviewError('另一个页面已保存新版本，请刷新后再操作；本页草稿可导出备份', 409)

    def draft(self, payload):
        with self.lock:
            self.check_source(); rows = self.selection(payload); self.check_revision(payload)
            if rows != self.state['selection']:
                state = copy.deepcopy(self.state)
                state.update(selection=rows, revision=state['revision'] + 1, status='draft', active_version=None, updated_at=now())
                self.save_state(state)
            return {'revision': self.state['revision'], 'status': self.state['status']}

    def make_plan(self, rows):
        p = copy.deepcopy(self.plan)
        p['plain_overrides'] = []
        for segment, row in zip(p['segments'], rows):
            segment['highlights'] = [{'start': a, 'end': b, 'text': segment['text'][a:b]} for a,b in row['ranges']]
            if not row['ranges']:
                p['plain_overrides'].append({'segment_id': segment['id'], 'reason': '网页整体确认：本句保持白字'})
        p['highlight_policy'] = {'version': 5, 'coverage_mode': 'informational', 'density_mode': 'warning',
            'max_consecutive_plain_segments': 1, 'fully_parenthetical_mode': 'plain_and_cadence_exempt',
            'user_plain_override_mode': 'plain_and_cadence_exempt'}
        errors = self.focus.validate_plan(p) + self.focus.validate_highlight_policy(p)[0]
        if errors: raise ReviewError('; '.join(errors))
        return p

    def confirm(self, payload):
        with self.lock:
            self.check_source(); rows = self.selection(payload)
            if payload.get('confirmed') is not True: raise ReviewError('需要用户明确点击确认')
            request_id = payload.get('request_id', '')
            if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', request_id): raise ReviewError('缺少有效提交编号')
            content_hash = digest(rows)
            for receipt_path in sorted(self.output.glob('v[0-9]*/receipt.json')):
                receipt = read(receipt_path)
                if receipt['request_id'] == request_id:
                    if receipt['selection_sha256'] != content_hash: raise ReviewError('同一提交编号不能用于不同内容', 409)
                    if self.state['revision'] == receipt['base_revision']:
                        state = copy.deepcopy(self.state)
                        state.update(selection=rows, revision=receipt['revision'], status='confirmed', active_version=receipt['version'], updated_at=now())
                        self.save_state(state)
                    if self.state['active_version'] != receipt['version']: raise ReviewError('该提交已有更新版本', 409)
                    self.start_sample(receipt['version'])
                    return receipt
            self.check_revision(payload)
            p = self.make_plan(rows)
            if self.video and self.focus.sha256_file(self.video) != self.config['video_sha256']:
                raise ReviewError('测试视频已变化，请重新建立会话', 409)
            if self.focus.sha256_file(self.style) != self.config['style_sha256']:
                raise ReviewError('字幕样式已变化，请重新建立会话', 409)
            numbers = [int(x.name[1:]) for x in self.output.glob('v[0-9]*') if x.is_dir() and x.name[1:].isdigit()]
            version = 'v%03d' % (max(numbers, default=0) + 1)
            dest = self.output / version
            temp = self.output / ('.pending-' + uuid.uuid4().hex)
            temp.mkdir()
            stamp = now()
            try:
                # The SRT snapshot is for durable Obsidian traceability. Runtime still
                # checks the locked source so edits cannot silently reuse approval.
                (temp / '字幕原文.srt').write_bytes(Path(self.plan['source_srt']).read_bytes())
                spec = {'kind': 'subtitle-focus-web-highlights', 'version': 1, 'source_sha256': self.plan['source_sha256'],
                        'plan_sha256': self.config['plan_sha256'], 'segments': rows, 'plain_overrides': p['plain_overrides']}
                atomic_json(temp / 'highlights.json', spec)
                p['highlight_source'] = str(dest / 'highlights.json')
                p['review_confirmation'] = {'receipt': str(dest / 'receipt.json'), 'state': str(self.state_path)}
                atomic_json(temp / 'caption-plan.json', p)
                md = self.markdown(rows, version, stamp)
                (temp / '字幕高亮确认记录.md').write_text(md, encoding='utf-8')
                receipt = {'kind': 'subtitle-focus-review-receipt', 'version': version, 'session_id': self.state['session_id'],
                           'confirmed': True, 'test_only': self.test_mode, 'confirmed_at': stamp,
                           'request_id': request_id, 'base_revision': self.state['revision'], 'revision': self.state['revision'] + 1,
                           'source_sha256': self.plan['source_sha256'], 'selection_sha256': content_hash,
                           'plan_sha256': plan_digest(p), 'files': {name: self.focus.sha256_file(temp / name) for name in
                           ['字幕原文.srt','highlights.json','caption-plan.json','字幕高亮确认记录.md']}, 'full_video_applied': False}
                atomic_json(temp / 'receipt.json', receipt)
                self.check_source()
                if self.focus.sha256_file(temp / '字幕原文.srt') != self.plan['source_sha256']:
                    raise ReviewError('保存期间源字幕发生变化，请重新审核', 409)
                # Publish the complete bundle in one directory rename, then its pointer.
                os.replace(temp, dest)
                state = copy.deepcopy(self.state)
                state.update(selection=rows, revision=receipt['revision'], status='confirmed', active_version=version, updated_at=stamp)
                self.save_state(state)
            finally:
                if temp.exists(): shutil.rmtree(temp)
            self.start_sample(version)
            return receipt

    def markdown(self, rows, version, stamp):
        title = html.escape(self.config['title'])
        lines = ['---','categories: [字幕审核]','rating: null',f'version: {version}',
                 'status: 已确认高亮方案',f'test_only: {str(self.test_mode).lower()}',f'confirmed_at: "{stamp}"','---','',
                 '# ' + title, '', '> 黄色标记代表本次确认的字幕黄色强调；这是高亮方案确认，尚不代表已用于全片。', '',
                 '- 字幕原文：[本版 SRT](<字幕原文.srt>)', '- 精确范围：[本版 JSON](highlights.json)', '- 确认凭据：[本版回执](receipt.json)',
                 '- 样片状态：[生成状态](sample-status.json)（生成后可查看）',
                 '- 源 SRT SHA-256：`' + self.plan['source_sha256'] + '`',
                 '- 分段方案 SHA-256：`' + self.config['plan_sha256'] + '`',
                 '- 确认时间（UTC）：' + stamp, '- 成片状态：未登记使用', '']
        if self.test_mode: lines += ['> [!WARNING] 链路验收材料', '> 测试确认不代表正式项目的校字、高亮或成片验收。','']
        for s,row in zip(self.plan['segments'],rows):
            # Escape Markdown metacharacters. <mark> is robust for whitespace and ==
            # inside the source; inline yellow also survives custom Obsidian themes.
            parts=[]; cursor=0
            def esc(t):
                return ''.join('\\'+c if c in '\\`*_{}[]()#+-.!|>' else html.escape(c) for c in t).replace('\n','<br>')
            for a,b in row['ranges']:
                parts += [esc(s['text'][cursor:a]), '<mark style="background-color:#FFD600;color:#171717">'+html.escape(s['text'][a:b]).replace('\n','<br>')+'</mark>']; cursor=b
            parts.append(esc(s['text'][cursor:]))
            lines += [f"**{self.focus.format_timecode(s['start_ms'])} → {self.focus.format_timecode(s['end_ms'])} · {s['id']}**",'', ''.join(parts), '']
        return '\n'.join(lines)

    def start_sample(self, version):
        if not self.video: return
        dest = self.output / version
        status_path = dest / 'sample-status.json'
        if self.worker and self.worker.is_alive(): return
        if status_path.exists() and read(status_path).get('status') == 'ready':
            existing = dest / 'sample.mp4'
            if existing.is_file() and self.focus.sha256_file(existing) == read(status_path).get('output_sha256'):
                return
        atomic_json(status_path, {'status': 'queued', 'version': version, 'test_only': self.test_mode})
        def run():
            try:
                atomic_json(status_path, {'status': 'rendering', 'version': version})
                partial = dest / 'sample.partial.mp4'
                partial.unlink(missing_ok=True)
                plan_path = dest / 'caption-plan.json'
                p = read(plan_path)
                start = next((s['start_ms']/1000 for s in p['segments'] if s['highlights']), p['segments'][0]['start_ms']/1000)
                command = [sys.executable, str(Path(__file__).with_name('subtitle_focus.py')), 'render', '--video', str(self.video),
                           '--plan', str(plan_path), '--style', str(self.style), '--output', str(partial), '--start', str(start),
                           '--duration', str(self.sample_seconds), '--preset', 'fast']
                result = subprocess.run(command, capture_output=True, text=True, timeout=600)
                (dest / 'sample-render.log').write_text(result.stdout + result.stderr, encoding='utf-8')
                if result.returncode: raise ReviewError(result.stderr[-1800:])
                verify_confirmation(p)
                self.check_source()
                if self.focus.sha256_file(self.video) != self.config['video_sha256'] or self.focus.sha256_file(self.style) != self.config['style_sha256']:
                    raise ReviewError('生成样片期间视频或样式发生变化')
                os.replace(partial, dest / 'sample.mp4')
                (dest / '样片生成记录.md').write_text('# 样片已生成，待人工验收\n\n[播放本版样片](sample.mp4)\n\n对应高亮：[本版高亮记录](<字幕高亮确认记录.md>)\n\n仅生成短样片，未烧录全片。\n',encoding='utf-8')
                atomic_json(status_path, {'status': 'ready', 'version': version, 'test_only': self.test_mode,
                     'output_sha256': self.focus.sha256_file(dest / 'sample.mp4'), 'plan_sha256': plan_digest(p),
                     'source_video_sha256': self.config['video_sha256'], 'start_seconds': start,
                     'duration_seconds': self.focus.probe_video(dest / 'sample.mp4')['duration'], 'sample_accepted': False})
            except Exception as e:
                atomic_json(status_path, {'status': 'error', 'version': version, 'message': str(e)})
            finally:
                with self.lock:
                    self.worker = None
                    next_version = self.state.get('active_version')
                    if next_version and next_version != version:
                        self.start_sample(next_version)
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()


def make_server(session, port=0):
    assets = Path(__file__).resolve().parents[1] / 'assets' / 'review'
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def respond(self, status, body, mime='application/json; charset=utf-8', headers=None):
            if not isinstance(body, bytes): body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            for k,v in (headers or {}).items(): self.send_header(k,v)
            self.end_headers(); self.wfile.write(body)
        def host_ok(self): return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
        def auth(self):
            return secrets.compare_digest(self.headers.get('X-Review-Token',''),session.token) or ('review_token='+session.token) in self.headers.get('Cookie','').split('; ')
        def do_GET(self):
            if not self.host_ok(): return self.respond(403,{'error':'Host rejected'})
            path=urlsplit(self.path).path
            static={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if path in static:
                name,mime=static[path];return self.respond(200,(assets/name).read_bytes(),mime)
            if not self.auth(): return self.respond(403,{'error':'本机审核会话已过期，请使用最新链接'})
            if path=='/api/session':
                return self.respond(200,session.public(),headers={'Set-Cookie':'review_token='+session.token+'; HttpOnly; SameSite=Strict; Path=/'})
            if path=='/api/status':
                try: session.check_source()
                except ReviewError as e: return self.respond(e.status,{'error':str(e)})
                return self.respond(200,session.public())
            if path=='/video' and session.video: return self.file(session.video,'video/mp4')
            m=re.fullmatch(r'/artifacts/(v\d{3,})/(record|sample|highlights)',path)
            if m:
                version,kind=m.groups()
                name,mime={'record':('字幕高亮确认记录.md','text/plain; charset=utf-8'),'sample':('sample.mp4','video/mp4'),'highlights':('highlights.json','application/json')}[kind]
                p=session.output/version/name
                if p.is_file() and (session.output/version/'receipt.json').exists(): return self.file(p,mime)
            return self.respond(404,{'error':'Not found'})
        def file(self,p,mime):
            size=p.stat().st_size;start=0;end=size-1;code=200
            ran=self.headers.get('Range')
            if ran:
                m=re.fullmatch(r'bytes=(\d+)-(\d*)',ran)
                if not m:return self.respond(416,{'error':'Invalid range'})
                start=int(m[1]);end=min(int(m[2]) if m[2] else end,end);code=206
                if start>end:return self.respond(416,{'error':'Invalid range'})
            self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store')
            if code==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with p.open('rb') as f:
                    f.seek(start);remain=end-start+1
                    while remain:
                        chunk=f.read(min(remain,65536))
                        if not chunk:break
                        self.wfile.write(chunk);remain-=len(chunk)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_POST(self):
            self.close_connection = True
            if not self.host_ok() or not self.auth() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':return self.respond(403,{'error':'本机确认请求来源无效'})
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':return self.respond(415,{'error':'JSON required'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000:raise ReviewError('请求过大或为空',413)
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ReviewError('请求必须是对象')
                path=urlsplit(self.path).path
                if path=='/api/draft': result=session.draft(payload)
                elif path=='/api/confirm':result=session.confirm(payload)
                else:raise ReviewError('Not found',404)
                self.respond(200,result)
            except ReviewError as e:self.respond(e.status,{'error':str(e)})
            except (ValueError,KeyError,TypeError) as e:self.respond(400,{'error':str(e)})
            except Exception:self.respond(500,{'error':'保存失败，未确认成功。请保留草稿并重试。'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def serve(args, focus):
    import fcntl
    output=Path(args.output_dir).expanduser().resolve();output.mkdir(parents=True,exist_ok=True)
    with (output/'.server.lock').open('a') as lockfile:
        try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise focus.FocusError('该审核目录已有服务运行，请使用现有链接')
        terms=read(args.terms) if args.terms else []
        if not isinstance(terms,list) or not all(isinstance(s,str) and s for s in terms):raise focus.FocusError('--terms 必须是词组字符串数组')
        try:
            session=ReviewSession(focus,args.plan,output,args.title,terms,args.video,args.style,args.sample_seconds,args.test_mode)
            server=make_server(session,args.port)
        except ReviewError as e:raise focus.FocusError(str(e))
        url=f'http://127.0.0.1:{server.server_port}/#token={session.token}'
        atomic_json(output/'connection.json',{'url':url,'pid':os.getpid(),'session_id':session.state['session_id']})
        os.chmod(output/'connection.json',0o600)
        print(json.dumps({'url':url,'output':str(output)},ensure_ascii=False),flush=True)
        if session.state.get('active_version'):session.start_sample(session.state['active_version'])
        try:server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:pass
        finally:server.server_close()
