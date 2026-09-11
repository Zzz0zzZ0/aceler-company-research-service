"""Local credential failover with process-safe persistence; no network calls."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

MAX_KEYS = 20


@contextmanager
def locked_state(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {'keys': [], 'active_id': None}
        yield state
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix='.' + path.name, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            temporary.replace(path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


def add_keys(path, keys):
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS:
        raise ValueError('每次输入 1–20 个 Key')
    if any(not isinstance(k, str) or not 8 <= len(k.strip()) <= 512
           or any(c.isspace() for c in k.strip()) for k in keys):
        raise ValueError('Key 长度必须为 8–512，且不能包含空白字符')
    keys = list(dict.fromkeys(k.strip() for k in keys))
    with locked_state(path) as state:
        known = {row['id'] for row in state['keys']}
        new = [{'id': hashlib.sha256(k.encode()).hexdigest()[:16], 'key': k,
                'status': 'ready', 'attempts': 0} for k in keys
               if hashlib.sha256(k.encode()).hexdigest()[:16] not in known]
        if len(state['keys']) + len(new) > MAX_KEYS:
            raise ValueError('最多保存 20 个 Key，请先移除不用的 Key')
        state['keys'].extend(new)
    return public_status(path)


def public_status(path):
    path = Path(path)
    if not path.exists():
        return {'configured': False, 'available': 0, 'keys': []}
    # Atomic replacement means readers see one complete version.
    state = json.loads(path.read_text())
    return {'configured': True, 'available': sum(k['status'] == 'ready' for k in state['keys']),
            'keys': [{'id': k['id'], 'masked': '••••' + k['key'][-4:], 'status': k['status'],
                      'active': k['id'] == state.get('active_id'), 'attempts': k.get('attempts', 0),
                      'exhausted_at': k.get('exhausted_at')} for k in state['keys']]}


def select_key(path):
    with locked_state(path) as state:
        available = [k for k in state['keys'] if k['status'] == 'ready']
        if not available:
            return None
        key = next((k for k in available if k['id'] == state.get('active_id')), available[0])
        state['active_id'] = key['id']
        key['attempts'] = key.get('attempts', 0) + 1
        return key['id'], key['key']


def mark_exhausted(path, key_id):
    with locked_state(path) as state:
        # An old in-flight failure only affects the key used by that request.
        for key in state['keys']:
            if key['id'] == key_id and key['status'] == 'ready':
                key.update(status='exhausted', exhausted_at=datetime.now(timezone.utc).isoformat())
                break


def change_key(path, key_id, action):
    if action not in ('reset', 'remove'):
        raise ValueError('未知 Key 操作')
    with locked_state(path) as state:
        key = next((k for k in state['keys'] if k['id'] == key_id), None)
        if key is None:
            raise ValueError('Key 不存在')
        if action == 'remove':
            state['keys'].remove(key)
        else:
            key['status'] = 'ready'
            key.pop('exhausted_at', None)
        if state.get('active_id') == key_id:
            state['active_id'] = None
    return public_status(path)
