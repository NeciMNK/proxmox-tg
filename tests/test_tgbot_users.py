# -*- coding: utf-8 -*-
"""Telegram bot: PegaProx users and Proxmox VE users, groups, roles and permissions (ACL).

The first half drives the bot's screens against a stand-in for PegaProx; the second half
sends the bot's client into the real PegaProx app, so the permission checks that matter
are PegaProx's own."""
import copy
import json as _json

import pytest

from tgbot.bot import Bot
from tgbot.config import Config
from tgbot.pegaprox_client import ApiError, PegaProx
from tgbot.store import Store

TOKEN = 'pgx_ab12_' + 'x' * 43
UID = 4242

ACCESS = {
    'users': [{'userid': 'root@pam', 'enable': 1, 'groups': [], 'protected': True},
              {'userid': 'anna@pve', 'enable': 1, 'groups': ['ops'], 'email': 'a@x.ru'}],
    'groups': [{'groupid': 'ops', 'comment': '', 'users': ['anna@pve']},
               {'groupid': 'dev', 'comment': '', 'users': []}],
    'roles': [{'roleid': 'PVEVMUser', 'special': True, 'privs': ['VM.Audit', 'VM.PowerMgmt']},
              {'roleid': 'Backup', 'special': False, 'privs': ['VM.Backup']}],
    'acl': [{'path': '/', 'type': 'user', 'ugid': 'root@pam', 'roleid': 'Administrator', 'propagate': 1},
            {'path': '/vms', 'type': 'group', 'ugid': 'ops', 'roleid': 'PVEVMUser', 'propagate': 1}],
    'realms': [{'realm': 'pam', 'type': 'pam'}, {'realm': 'pve', 'type': 'pve'}],
    'privileges': ['VM.Audit', 'VM.Backup', 'VM.PowerMgmt'],
}
PANEL = [{'username': 'nikita', 'role': 'admin', 'enabled': True, 'tenant_id': 'default', 'auth_source': 'local'},
         {'username': 'olga', 'role': 'viewer', 'enabled': True, 'tenant_id': 'default', 'auth_source': 'local',
          'totp_enabled': True}]


class FakeTG:
    def __init__(self):
        self.sent, self.edited, self.deleted = [], [], []

    def send(self, chat, text, keyboard=None, **kw):
        self.sent.append((chat, text, keyboard))
        return {'message_id': len(self.sent)}

    def edit(self, chat, mid, text, keyboard=None):
        self.edited.append((chat, mid, text, keyboard))

    def delete(self, chat, mid):
        self.deleted.append((chat, mid))

    def answer(self, *a, **kw):
        pass

    def set_commands(self, commands):
        pass


class FakeApi:
    def __init__(self, token, calls, deny):
        self.calls, self.deny = calls, deny

    def _rec(self, name, *a):
        self.calls.append((name,) + a)
        if name in self.deny:
            raise ApiError(403, 'Permission denied')

    def me(self):
        return {'role': 'admin', 'permissions': []}

    def clusters(self):
        return [{'id': 'c1', 'name': 'pve', 'display_name': 'Дом', 'connected': True}]

    def vms(self, cid):
        return [{'vmid': 101, 'name': 'web', 'node': 'pve1', 'type': 'qemu', 'status': 'running'}]

    def pve_access(self, cid):
        self._rec('pve_access', cid)
        return copy.deepcopy(ACCESS)

    def create_pve_user(self, cid, fields):
        self._rec('create_pve_user', cid, fields)

    def update_pve_user(self, cid, userid, fields):
        self._rec('update_pve_user', cid, userid, fields)

    def delete_pve_user(self, cid, userid):
        self._rec('delete_pve_user', cid, userid)

    def set_pve_password(self, cid, userid, password):
        self._rec('set_pve_password', cid, userid, password)

    def create_pve_group(self, cid, groupid, comment=''):
        self._rec('create_pve_group', cid, groupid, comment)

    def create_pve_role(self, cid, roleid, privs):
        self._rec('create_pve_role', cid, roleid, privs)

    def set_pve_acl(self, cid, path, roles, users=(), groups=(), tokens=(), propagate=True, delete=False):
        self._rec('set_pve_acl', cid, path, list(roles), list(users), list(groups), list(tokens), propagate, delete)

    def panel_users(self):
        self._rec('panel_users')
        return copy.deepcopy(PANEL)

    def panel_roles(self):
        return [{'id': 'admin', 'name': 'Admin'}, {'id': 'user', 'name': 'User'}, {'id': 'viewer', 'name': 'Viewer'}]

    def create_panel_user(self, username, password, role, display_name='', email=''):
        self._rec('create_panel_user', username, password, role)

    def update_panel_user(self, username, fields):
        self._rec('update_panel_user', username, fields)

    def set_panel_password(self, username, password):
        self._rec('set_panel_password', username, password)

    def reset_panel_2fa(self, username):
        self._rec('reset_panel_2fa', username)

    def delete_panel_user(self, username):
        self._rec('delete_panel_user', username)


@pytest.fixture
def env(tmp_path):
    cfg = Config(bot_token='1:x', data_dir=str(tmp_path / 'data'), alert_poll=0)
    tg, calls, deny = FakeTG(), [], set()
    bot = Bot(cfg, tg, Store(cfg.data_dir), api_factory=lambda t: FakeApi(t, calls, deny))
    bot.store.link(UID, TOKEN)
    return bot, tg, calls, deny


def msg(text, chat_type='private', mid=10):
    return {'message': {'message_id': mid, 'from': {'id': UID}, 'chat': {'id': UID, 'type': chat_type}, 'text': text}}


def press(bot, button):
    bot.handle_update({'callback_query': {'id': 'q', 'from': {'id': UID}, 'data': button['callback_data'],
                                          'message': {'message_id': 99, 'chat': {'id': UID}}}})


def tap(bot, tg, label):
    _text, kb = current(tg)
    for row in kb or []:
        for b in row:
            if label in b['text']:
                press(bot, b)
                return
    raise AssertionError(f'no button {label!r} in {[b["text"] for row in kb or [] for b in row]}')


def current(tg):
    """The screen the user looks at now: the last thing the bot sent or edited."""
    return tg.last


@pytest.fixture(autouse=True)
def _track(monkeypatch):
    orig_send, orig_edit = FakeTG.send, FakeTG.edit

    def send(self, chat, text, keyboard=None, **kw):
        self.last = (text, keyboard)
        return orig_send(self, chat, text, keyboard, **kw)

    def edit(self, chat, mid, text, keyboard=None):
        self.last = (text, keyboard)
        return orig_edit(self, chat, mid, text, keyboard)

    monkeypatch.setattr(FakeTG, 'send', send)
    monkeypatch.setattr(FakeTG, 'edit', edit)


# --- Proxmox VE --------------------------------------------------------------------------

def open_pve(bot, tg):
    bot.handle_update(msg('/users'))
    tap(bot, tg, 'Proxmox: Дом')


def test_users_command_offers_both_kinds(env):
    bot, tg, _, _ = env
    bot.handle_update(msg('/users'))
    text, kb = current(tg)
    labels = [b['text'] for row in kb for b in row]
    assert any('PegaProx' in x for x in labels) and any('Proxmox: Дом' in x for x in labels)


def test_a_refusal_explains_who_may_manage_users(env):
    bot, tg, calls, deny = env
    deny.add('pve_access')
    open_pve(bot, tg)
    assert 'администратор PegaProx' in current(tg)[0]


def test_create_a_pve_user_with_a_password_that_is_deleted(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Новый пользователь')
    bot.handle_update(msg('bad name'))
    assert 'имя@realm' in current(tg)[0]
    bot.handle_update(msg('ivan@pve'))
    assert 'Пароль' in current(tg)[0]
    bot.handle_update(msg('s3cret-pass', mid=77))
    assert (UID, 77) in tg.deleted
    assert ('create_pve_user', 'c1', {'userid': 'ivan@pve', 'password': 's3cret-pass'}) in calls
    assert not any('s3cret-pass' in t for _, t, _ in tg.sent)


def test_a_password_is_never_taken_in_a_group(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Пользователи')
    tap(bot, tg, 'anna@pve')
    tap(bot, tg, 'Пароль')
    bot.handle_update(msg('s3cret-pass', chat_type='group', mid=5))
    assert (UID, 5) in tg.deleted
    assert not any(c[0] == 'set_pve_password' for c in calls)
    assert 'личном чате' in current(tg)[0]


def test_root_pam_cannot_be_disabled_or_deleted_from_the_bot(env):
    bot, tg, _, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Пользователи')
    tap(bot, tg, 'root@pam')
    labels = [b['text'] for row in current(tg)[1] for b in row]
    assert not any('Удалить' in x or 'Выключить' in x for x in labels)


def test_toggle_group_membership(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Пользователи')
    tap(bot, tg, 'anna@pve')
    tap(bot, tg, 'Группы')
    tap(bot, tg, '▫️ dev')
    assert ('update_pve_user', 'c1', 'anna@pve', {'groups': ['ops', 'dev']}) in calls
    tap(bot, tg, '✅ ops')
    assert ('update_pve_user', 'c1', 'anna@pve', {'groups': []}) in calls


def test_grant_a_role_on_one_vm_step_by_step(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Права (ACL)')
    tap(bot, tg, 'Выдать права')
    tap(bot, tg, '@dev')
    tap(bot, tg, 'PVEVMUser')
    tap(bot, tg, 'Одна VM/CT')
    tap(bot, tg, '101 web')
    assert '/vms/101' in current(tg)[0]
    assert not any(c[0] == 'set_pve_acl' for c in calls)
    tap(bot, tg, '✅ Выдать')
    assert ('set_pve_acl', 'c1', '/vms/101', ['PVEVMUser'], [], ['dev'], [], True, False) in calls


def test_a_typed_path_is_checked(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Пользователи')
    tap(bot, tg, 'anna@pve')
    tap(bot, tg, 'Выдать права')
    tap(bot, tg, 'PVEVMUser')
    tap(bot, tg, 'Ввести путь')
    bot.handle_update(msg('vms/1/../..'))
    assert 'Путь начинается с /' in current(tg)[0]
    bot.handle_update(msg('/storage/local'))
    tap(bot, tg, 'без вложенных')
    assert ('set_pve_acl', 'c1', '/storage/local', ['PVEVMUser'], ['anna@pve'], [], [], False, False) in calls


def test_remove_a_permission_asks_first(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Права (ACL)')
    tap(bot, tg, '🗑 2')
    assert not any(c[0] == 'set_pve_acl' for c in calls)
    tap(bot, tg, 'Да, забрать')
    assert ('set_pve_acl', 'c1', '/vms', ['PVEVMUser'], [], ['ops'], [], True, True) in calls


def test_new_group_and_role(env):
    bot, tg, calls, _ = env
    open_pve(bot, tg)
    tap(bot, tg, 'Группы')
    tap(bot, tg, 'Создать')
    bot.handle_update(msg('admins Администраторы'))
    assert ('create_pve_group', 'c1', 'admins', 'Администраторы') in calls
    open_pve(bot, tg)
    tap(bot, tg, 'Роли')
    tap(bot, tg, 'Своя роль')
    bot.handle_update(msg('Power VM.PowerMgmt, VM.Nope'))
    assert 'VM.Nope' in current(tg)[0]
    bot.handle_update(msg('Power VM.PowerMgmt,VM.Audit'))
    assert ('create_pve_role', 'c1', 'Power', ['VM.Audit', 'VM.PowerMgmt']) in calls


# --- PegaProx ----------------------------------------------------------------------------

def open_panel(bot, tg):
    bot.handle_update(msg('/users'))
    tap(bot, tg, 'Пользователи PegaProx')


def test_create_a_panel_user(env):
    bot, tg, calls, _ = env
    open_panel(bot, tg)
    tap(bot, tg, 'Создать')
    bot.handle_update(msg('Ivan'))
    tap(bot, tg, 'Viewer')
    bot.handle_update(msg('Passw0rd!', mid=31))
    assert (UID, 31) in tg.deleted
    assert ('create_panel_user', 'ivan', 'Passw0rd!', 'viewer') in calls


def test_change_role_disable_and_reset_2fa(env):
    bot, tg, calls, _ = env
    open_panel(bot, tg)
    tap(bot, tg, 'olga')
    tap(bot, tg, 'Роль')
    tap(bot, tg, 'User')
    assert ('update_panel_user', 'olga', {'role': 'user'}) in calls
    tap(bot, tg, 'Выключить')
    assert not any(c[0] == 'update_panel_user' and 'enabled' in c[2] for c in calls)
    tap(bot, tg, 'Да, выключить')
    assert ('update_panel_user', 'olga', {'enabled': False}) in calls
    tap(bot, tg, 'Сбросить 2FA')
    tap(bot, tg, 'Да, сбросить')
    assert ('reset_panel_2fa', 'olga') in calls


def test_panel_refusal_names_the_permission(env):
    bot, tg, _, deny = env
    deny.add('panel_users')
    open_panel(bot, tg)
    assert 'admin.users' in current(tg)[0]


# --- against the real PegaProx ------------------------------------------------------------

class _Resp:
    def __init__(self, r):
        self.status_code = r.status_code
        self._r = r

    def json(self):
        data = self._r.get_json(silent=True)
        if data is None:
            raise ValueError('no json')
        return data


class _FlaskSession:
    def __init__(self, client):
        self.client = client

    def request(self, method, url, json=None, params=None, headers=None, **_kw):
        path = url.split('://', 1)[1].split('/', 1)[1]
        return _Resp(self.client.open('/' + path, method=method, json=json, query_string=params,
                                      headers=headers, base_url='http://localhost'))


class _PveResp:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.text = _json.dumps({'data': data})

    def json(self):
        return {'data': self._data}


class _PveSession:
    def __init__(self, calls):
        self.calls = calls

    def _do(self, method, url, data=None, params=None, timeout=None):
        path = url.split('/api2/json/access/', 1)[1]
        self.calls.append((method, path, data))
        return _PveResp([] if method == 'get' else None)

    def get(self, url, **kw): return self._do('get', url, **kw)
    def post(self, url, **kw): return self._do('post', url, **kw)
    def put(self, url, **kw): return self._do('put', url, **kw)
    def delete(self, url, **kw): return self._do('delete', url, **kw)


def _client(api, token):
    return PegaProx('http://localhost', token, session=_FlaskSession(api.app.test_client()))


@pytest.fixture
def pve_cluster(api):
    calls = []
    m = api.make_fake_manager('c1')
    m.config.name = 'c1'
    m.host, m.api_port = 'pve1', 8006
    m._create_session.side_effect = lambda: _PveSession(calls)
    api.set_manager('c1', m)
    return calls


def test_an_admin_token_grants_a_pve_role_from_telegram(api, seed, pve_cluster):
    from pegaprox.utils.auth import create_api_token
    seed.user('nikita', role='admin')
    token = create_api_token('nikita', 'telegram')['token']
    _client(api, token).set_pve_acl('c1', '/vms/101', ['PVEVMUser'], groups=['dev'])
    put = [c for c in pve_cluster if c[0] == 'put' and c[1] == 'acl']
    assert put and put[0][2]['groups'] == 'dev' and put[0][2]['path'] == '/vms/101'


def test_a_viewer_token_cannot_touch_pve_users(api, seed, pve_cluster):
    from pegaprox.utils.auth import create_api_token
    seed.user('nikita', role='admin')
    token = create_api_token('nikita', 'telegram', role='viewer')['token']
    with pytest.raises(ApiError) as err:
        _client(api, token).create_pve_user('c1', {'userid': 'x@pve'})
    assert err.value.status == 403
    assert not any(c[0] == 'post' for c in pve_cluster)


def test_panel_users_through_the_bot_client(api, seed):
    from pegaprox.utils.auth import create_api_token
    seed.user('nikita', role='admin')
    token = create_api_token('nikita', 'telegram')['token']
    c = _client(api, token)
    c.create_panel_user('ivan', 'Passw0rd!x', 'viewer')
    assert any(u['username'] == 'ivan' and u['role'] == 'viewer' for u in c.panel_users())
    c.update_panel_user('ivan', {'role': 'user'})
    assert next(u for u in c.panel_users() if u['username'] == 'ivan')['role'] == 'user'
    c.delete_panel_user('ivan')
    assert not any(u['username'] == 'ivan' for u in c.panel_users())


def test_a_viewer_token_cannot_create_panel_users(api, seed):
    from pegaprox.utils.auth import create_api_token
    seed.user('nikita', role='admin')
    token = create_api_token('nikita', 'telegram', role='viewer')['token']
    with pytest.raises(ApiError) as err:
        _client(api, token).create_panel_user('ivan', 'Passw0rd!x', 'admin')
    assert err.value.status == 403
