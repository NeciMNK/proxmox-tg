# -*- coding: utf-8 -*-
"""Proxmox VE users, groups, roles and permissions (ACL) from Telegram - proxmox-tg fork.

The screens call /api/clusters/<id>/pve-access (pegaprox/api/pve_access.py) under the
linked user's own token, so PegaProx decides who may do this: only its administrators,
and only with a token that has the admin role. A refusal is shown, never worked around.
Everything that changes the cluster is written to the PegaProx audit log by those routes.
"""
import re

from . import views as v
from .pegaprox_client import ApiError

USERID_RE = re.compile(r'^[^\s:/@]{1,60}@[A-Za-z][A-Za-z0-9._-]{0,31}$')
ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
PATH_RE = re.compile(r'^/(?:[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)?$')
PROTECTED = ('root@pam',)
UPAGE = 10
APAGE = 12
# Paths offered as buttons when granting a role; anything else can be typed.
PATHS = [('/', 'весь кластер'), ('/vms', 'все VM и CT'), ('/storage', 'все хранилища'),
         ('/nodes', 'все ноды'), ('/pool', 'все пулы'), ('/sdn', 'SDN')]
ADMIN_HINT = ('Управлять пользователями Proxmox может только администратор PegaProx, '
              'и токен бота тоже должен иметь роль admin (Мой профиль → API-токены).')


class PveUsersMixin:
    """Mixed into tgbot.bot.Bot: uses its btn, screen, error, _do, pending and api."""

    # ------------------------------------------------------------------ helpers
    def _pve_load(self, uid, chat, mid, cid, cname, back=None):
        """The cluster's users/groups/roles/ACL, or None after showing why not."""
        try:
            return self.api(uid).pve_access(cid)
        except ApiError as err:
            name, ctx = back or ('cluster', dict(cid=cid, cname=cname))
            kb = [[self.btn(uid, '« Назад', name, **ctx)]]
            if err.status == 403:
                self.screen(chat, mid, f'⛔ {ADMIN_HINT}\n\n{v.e(err.message)}', kb)
            else:
                self.error(chat, err, mid, kb)
            return None

    @staticmethod
    def _acl_who(a):
        return ('👥 @' if a.get('type') == 'group' else ('🔑 ' if a.get('type') == 'token' else '👤 ')) + (a.get('ugid') or '')

    @staticmethod
    def _acl_line(a, who=True):
        inherit = '' if a.get('propagate', 1) else ' (без наследования)'
        subject = f'{v.e(PveUsersMixin._acl_who(a))} → ' if who else ''
        return f"{subject}<b>{v.e(a.get('roleid'))}</b> на <code>{v.e(a.get('path'))}</code>{inherit}"

    def _ask(self, uid, chat, mid, pend, text, kb):
        self.pending[uid] = pend
        return self.screen(chat, mid, text, kb)

    # ------------------------------------------------------------------ entry
    def cb_pve(self, uid, chat, mid, cid, cname):
        d = self._pve_load(uid, chat, mid, cid, cname)
        if d is None:
            return
        c = dict(cid=cid, cname=cname)
        users = d.get('users') or []
        off = sum(1 for u in users if not u.get('enable', 1))
        realms = ', '.join(r.get('realm') or '' for r in d.get('realms') or [])
        text = (f'<b>{v.e(cname)}: пользователи и права Proxmox</b>\n'
                f"Пользователей: {len(users)}" + (f' (выключено {off})' if off else '') + '\n'
                f"Групп: {len(d.get('groups') or [])}, ролей: {len(d.get('roles') or [])}, "
                f"записей прав: {len(d.get('acl') or [])}\n"
                f"Realm: {v.e(realms)}")
        kb = [[self.btn(uid, '👤 Пользователи', 'pve_users', **c), self.btn(uid, '👥 Группы', 'pve_groups', **c)],
              [self.btn(uid, '🎭 Роли', 'pve_roles', **c), self.btn(uid, '🔑 Права (ACL)', 'pve_acl', **c)],
              [self.btn(uid, '➕ Новый пользователь', 'pve_user_new', **c)],
              [self.btn(uid, '🔄 Обновить', 'pve', **c), self.btn(uid, '« Кластер', 'cluster', **c)]]
        return self.screen(chat, mid, text, kb)

    # ------------------------------------------------------------------ users
    def cb_pve_users(self, uid, chat, mid, cid, cname, page=0):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve', c))
        if d is None:
            return
        users = d.get('users') or []
        pages = max(1, (len(users) + UPAGE - 1) // UPAGE)
        page = min(max(0, page), pages - 1)
        kb = [[self.btn(uid, f"{'🟢' if u.get('enable', 1) else '⚪'} {u['userid']}"[:60], 'pve_user',
                        userid=u['userid'], **c)] for u in users[page * UPAGE:(page + 1) * UPAGE]]
        nav = []
        if page > 0:
            nav.append(self.btn(uid, '‹', 'pve_users', page=page - 1, **c))
        if page < pages - 1:
            nav.append(self.btn(uid, '›', 'pve_users', page=page + 1, **c))
        if nav:
            kb.append(nav)
        kb.append([self.btn(uid, '➕ Создать', 'pve_user_new', **c), self.btn(uid, '« Назад', 'pve', **c)])
        return self.screen(chat, mid, f'<b>{v.e(cname)}: пользователи Proxmox</b> ({len(users)}), '
                                      f'стр. {page + 1}/{pages}\n🟢 включён, ⚪ выключен', kb)

    def cb_pve_user(self, uid, chat, mid, cid, cname, userid):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_users', c))
        if d is None:
            return
        u = next((x for x in d.get('users') or [] if x.get('userid') == userid), None)
        if not u:
            return self.screen(chat, mid, f'Пользователь {v.e(userid)} не найден.',
                               [[self.btn(uid, '« Пользователи', 'pve_users', **c)]])
        name = ' '.join(x for x in (u.get('firstname'), u.get('lastname')) if x)
        groups = u.get('groups') or []
        mine = [a for a in d.get('acl') or [] if (a.get('type') == 'user' and a.get('ugid') == userid)
                or (a.get('type') == 'group' and a.get('ugid') in groups)]
        lines = [f"👤 <b>{v.e(userid)}</b>" + (f' ({v.e(name)})' if name else ''),
                 f"Состояние: {'🟢 включён' if u.get('enable', 1) else '⚪ выключен'}",
                 f"Срок действия: {v.when(u['expire']) if u.get('expire') else 'бессрочно'}",
                 f"Realm: {v.e(userid.split('@', 1)[1])}" + (f" ({v.e(u['realm_type'])})" if u.get('realm_type') else '')]
        if u.get('email'):
            lines.append(f"E-mail: {v.e(u['email'])}")
        if u.get('comment'):
            lines.append(f"Комментарий: {v.e(u['comment'])}")
        lines.append(f"Группы: {v.e(', '.join(groups)) if groups else 'нет'}")
        if u.get('tokens'):
            lines.append(f"API-токены: {v.e(', '.join(u['tokens']))}")
        lines += ['', '<b>Права</b>'] + ([self._acl_line(a, who=a.get('type') == 'group') for a in mine]
                                         or ['нет (пользователь ничего не видит)'])
        u_ctx = dict(userid=userid, **c)
        kb = []
        if userid not in PROTECTED:
            kb.append([self.btn(uid, '⚪ Выключить' if u.get('enable', 1) else '🟢 Включить', 'pve_user_enable',
                                on=not u.get('enable', 1), **u_ctx)])
        kb.append([self.btn(uid, '👥 Группы', 'pve_user_groups', **u_ctx),
                   self.btn(uid, '🔑 Выдать права', 'pve_grant', grant={'type': 'user', 'ugid': userid}, **c)])
        row = []
        if userid.endswith('@pve'):
            row.append(self.btn(uid, '🔐 Пароль', 'pve_user_pw', **u_ctx))
        if mine:
            row.append(self.btn(uid, '➖ Забрать права', 'pve_acl', subject=('user', userid), **c))
        if row:
            kb.append(row)
        if userid not in PROTECTED:
            kb.append([self.btn(uid, '🗑 Удалить', 'pve_user_del', **u_ctx)])
        kb.append([self.btn(uid, '🔄 Обновить', 'pve_user', **u_ctx), self.btn(uid, '« Пользователи', 'pve_users', **c)])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_pve_user_enable(self, uid, chat, mid, cid, cname, userid, on, ok=False):
        u_ctx = dict(cid=cid, cname=cname, userid=userid)
        if not on and not ok:
            kb = [[self.btn(uid, '✅ Да, выключить', 'pve_user_enable', on=on, ok=True, **u_ctx),
                   self.btn(uid, 'Отмена', 'pve_user', **u_ctx)]]
            return self.screen(chat, mid, f'Выключить <b>{v.e(userid)}</b>? Он не сможет войти в Proxmox, '
                                          'его API-токены тоже перестанут работать.', kb)
        try:
            self.api(uid).update_pve_user(cid, userid, {'enable': bool(on)})
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, '« Назад', 'pve_user', **u_ctx)]])
        return self.cb_pve_user(uid, chat, mid, **u_ctx)

    def cb_pve_user_groups(self, uid, chat, mid, cid, cname, userid):
        u_ctx = dict(cid=cid, cname=cname, userid=userid)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_user', u_ctx))
        if d is None:
            return
        u = next((x for x in d.get('users') or [] if x.get('userid') == userid), None)
        if not u:
            return self.screen(chat, mid, f'Пользователь {v.e(userid)} не найден.',
                               [[self.btn(uid, '« Пользователи', 'pve_users', cid=cid, cname=cname)]])
        have = set(u.get('groups') or [])
        groups = [g['groupid'] for g in d.get('groups') or []]
        kb, row = [], []
        for g in groups:
            row.append(self.btn(uid, f"{'✅' if g in have else '▫️'} {g}"[:60], 'pve_member',
                                groupid=g, add=g not in have, back='user', **u_ctx))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([self.btn(uid, '➕ Новая группа', 'pve_group_new', cid=cid, cname=cname),
                   self.btn(uid, '« Назад', 'pve_user', **u_ctx)])
        text = (f'<b>Группы {v.e(userid)}</b>\nНажмите на группу, чтобы добавить в неё или убрать.'
                if groups else f'В кластере нет групп. Создайте первую.')
        return self.screen(chat, mid, text, kb)

    def cb_pve_member(self, uid, chat, mid, cid, cname, userid, groupid, add, back='user'):
        """Add a user to a group or take them out: Proxmox keeps membership on the user."""
        c = dict(cid=cid, cname=cname)
        here = ('pve_user_groups', dict(userid=userid, **c)) if back == 'user' else ('pve_group', dict(groupid=groupid, **c))
        api = self.api(uid)
        try:
            d = api.pve_access(cid)
            u = next((x for x in d.get('users') or [] if x.get('userid') == userid), None)
            if not u:
                raise ApiError(404, f'Пользователь {userid} не найден')
            groups = [g for g in u.get('groups') or [] if g != groupid] + ([groupid] if add else [])
            api.update_pve_user(cid, userid, {'groups': groups})
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, '« Назад', here[0], **here[1])]])
        return getattr(self, f'cb_{here[0]}')(uid, chat, mid, **here[1])

    def cb_pve_user_pw(self, uid, chat, mid, cid, cname, userid):
        u_ctx = dict(cid=cid, cname=cname, userid=userid)
        return self._ask(uid, chat, mid, {'kind': 'pve_password', 'u': u_ctx},
                         f'Пришлите новый пароль для <b>{v.e(userid)}</b> (8–256 символов).\n'
                         'Только в личном чате: сообщение с паролем я сразу удалю.',
                         [[self.btn(uid, 'Отмена', 'pve_user', **u_ctx)]])

    def cb_pve_user_del(self, uid, chat, mid, cid, cname, userid, ok=False):
        c = dict(cid=cid, cname=cname)
        if not ok:
            kb = [[self.btn(uid, '✅ Да, удалить', 'pve_user_del', userid=userid, ok=True, **c),
                   self.btn(uid, 'Отмена', 'pve_user', userid=userid, **c)]]
            return self.screen(chat, mid, f'Удалить пользователя <b>{v.e(userid)}</b> вместе с его '
                                          'API-токенами и правами? Это не отменить.', kb)
        return self._do(uid, chat, mid, lambda a: a.delete_pve_user(cid, userid),
                        f'Пользователь {v.e(userid)} удалён', back=('pve_users', c))

    def cb_pve_user_new(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve', c))
        if d is None:
            return
        realms = [r for r in d.get('realms') or [] if r.get('realm')]
        hint = '\n'.join(f"• <code>@{v.e(r['realm'])}</code> {v.e(r.get('comment') or r.get('type') or '')}"
                         for r in realms)
        return self._ask(uid, chat, mid, {'kind': 'pve_userid', 'c': c},
                         '<b>Новый пользователь Proxmox</b>\nПришлите имя в виде <code>имя@realm</code>, '
                         'например <code>ivan@pve</code>.\n'
                         'Для realm <b>pve</b> пароль хранит Proxmox, его спрошу следующим шагом. '
                         'Пользователь <b>pam</b> должен уже существовать в Linux на ноде.\n\n'
                         f'Realm в кластере:\n{hint}',
                         [[self.btn(uid, 'Отмена', 'pve', **c)]])

    def cb_pve_user_create(self, uid, chat, mid, cid, cname, userid, password=None):
        self.pending.pop(uid, None)
        fields = {'userid': userid}
        if password:
            fields['password'] = password
        try:
            self.api(uid).create_pve_user(cid, fields)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, '« Пользователи', 'pve_users', cid=cid, cname=cname)]])
        self.screen(chat, mid, f'✅ Пользователь <b>{v.e(userid)}</b> создан. Пока у него нет прав: '
                               'добавьте его в группу или выдайте роль.', None)
        return self.cb_pve_user(uid, chat, None, cid=cid, cname=cname, userid=userid)

    # ------------------------------------------------------------------ groups
    def cb_pve_groups(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve', c))
        if d is None:
            return
        groups = d.get('groups') or []
        lines = [f'<b>{v.e(cname)}: группы Proxmox</b>'] + (
            [f"👥 <b>{v.e(g['groupid'])}</b>: {len(g.get('users') or [])} чел."
             + (f" ({v.e(g['comment'])})" if g.get('comment') else '') for g in groups] or ['Групп нет'])
        kb = [[self.btn(uid, f"👥 {g['groupid']}"[:60], 'pve_group', groupid=g['groupid'], **c)] for g in groups[:40]]
        kb.append([self.btn(uid, '➕ Создать', 'pve_group_new', **c), self.btn(uid, '« Назад', 'pve', **c)])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_pve_group(self, uid, chat, mid, cid, cname, groupid):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_groups', c))
        if d is None:
            return
        g = next((x for x in d.get('groups') or [] if x.get('groupid') == groupid), None)
        if not g:
            return self.screen(chat, mid, f'Группа {v.e(groupid)} не найдена.',
                               [[self.btn(uid, '« Группы', 'pve_groups', **c)]])
        members = g.get('users') or []
        rights = [a for a in d.get('acl') or [] if a.get('type') == 'group' and a.get('ugid') == groupid]
        lines = [f"👥 <b>{v.e(groupid)}</b>" + (f" ({v.e(g['comment'])})" if g.get('comment') else ''),
                 f"Участники: {v.e(', '.join(members)) if members else 'нет'}", '', '<b>Права группы</b>'] + \
                ([self._acl_line(a, who=False) for a in rights] or ['нет'])
        g_ctx = dict(groupid=groupid, **c)
        kb = [[self.btn(uid, f'➖ {m}'[:60], 'pve_member', userid=m, add=False, back='group', **g_ctx)]
              for m in members[:20]]
        kb.append([self.btn(uid, '➕ Добавить участника', 'pve_group_add', **g_ctx),
                   self.btn(uid, '🔑 Выдать права', 'pve_grant', grant={'type': 'group', 'ugid': groupid}, **c)])
        if rights:
            kb.append([self.btn(uid, '➖ Забрать права', 'pve_acl', subject=('group', groupid), **c)])
        kb.append([self.btn(uid, '🗑 Удалить группу', 'pve_group_del', **g_ctx),
                   self.btn(uid, '« Группы', 'pve_groups', **c)])
        return self.screen(chat, mid, '\n'.join(lines) + ('\n\nКнопка ➖ убирает участника из группы.' if members else ''), kb)

    def cb_pve_group_add(self, uid, chat, mid, cid, cname, groupid):
        g_ctx = dict(cid=cid, cname=cname, groupid=groupid)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_group', g_ctx))
        if d is None:
            return
        out = [u['userid'] for u in d.get('users') or [] if groupid not in (u.get('groups') or [])]
        if not out:
            return self.screen(chat, mid, 'Все пользователи уже в этой группе.',
                               [[self.btn(uid, '« Назад', 'pve_group', **g_ctx)]])
        kb = [[self.btn(uid, f'➕ {u}'[:60], 'pve_member', userid=u, add=True, back='group', **g_ctx)] for u in out[:40]]
        kb.append([self.btn(uid, 'Отмена', 'pve_group', **g_ctx)])
        return self.screen(chat, mid, f'Кого добавить в группу <b>{v.e(groupid)}</b>?', kb)

    def cb_pve_group_new(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        return self._ask(uid, chat, mid, {'kind': 'pve_groupid', 'c': c},
                         'Пришлите имя новой группы (латиница, цифры, точка, - и _), можно с комментарием '
                         'через пробел: <code>admins Администраторы</code>',
                         [[self.btn(uid, 'Отмена', 'pve_groups', **c)]])

    def cb_pve_group_del(self, uid, chat, mid, cid, cname, groupid, ok=False):
        c = dict(cid=cid, cname=cname)
        if not ok:
            kb = [[self.btn(uid, '✅ Да, удалить', 'pve_group_del', groupid=groupid, ok=True, **c),
                   self.btn(uid, 'Отмена', 'pve_group', groupid=groupid, **c)]]
            return self.screen(chat, mid, f'Удалить группу <b>{v.e(groupid)}</b>? Участники останутся, '
                                          'а права, выданные группе, пропадут.', kb)
        return self._do(uid, chat, mid, lambda a: a.delete_pve_group(cid, groupid),
                        f'Группа {v.e(groupid)} удалена', back=('pve_groups', c))

    # ------------------------------------------------------------------ roles
    def cb_pve_roles(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve', c))
        if d is None:
            return
        roles = d.get('roles') or []
        own = [r for r in roles if not r.get('special')]
        builtin = [r for r in roles if r.get('special')]
        lines = [f'<b>{v.e(cname)}: роли Proxmox</b>', '', '<b>Свои роли</b>'] + (
            [f"🎭 <b>{v.e(r['roleid'])}</b>: {len(r.get('privs') or [])} привилегий" for r in own] or ['нет']) + \
            ['', '<b>Встроенные</b>: ' + v.e(', '.join(r['roleid'] for r in builtin))]
        kb, row = [], []
        for r in own + builtin:
            row.append(self.btn(uid, f"{'🎭' if not r.get('special') else '📘'} {r['roleid']}"[:40], 'pve_role',
                                roleid=r['roleid'], **c))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([self.btn(uid, '➕ Своя роль', 'pve_role_new', **c), self.btn(uid, '« Назад', 'pve', **c)])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_pve_role(self, uid, chat, mid, cid, cname, roleid):
        c = dict(cid=cid, cname=cname)
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_roles', c))
        if d is None:
            return
        r = next((x for x in d.get('roles') or [] if x.get('roleid') == roleid), None)
        if not r:
            return self.screen(chat, mid, f'Роль {v.e(roleid)} не найдена.', [[self.btn(uid, '« Роли', 'pve_roles', **c)]])
        used = [a for a in d.get('acl') or [] if a.get('roleid') == roleid]
        text = (f"{'📘 Встроенная роль' if r.get('special') else '🎭 Роль'} <b>{v.e(roleid)}</b>\n"
                f"Привилегии ({len(r.get('privs') or [])}): <code>{v.e(', '.join(r.get('privs') or []) or 'нет')}</code>\n"
                f"Выдана: {len(used)} раз")
        kb = []
        if not r.get('special'):
            kb.append([self.btn(uid, '✏️ Изменить привилегии', 'pve_role_edit', roleid=roleid, **c),
                       self.btn(uid, '🗑 Удалить', 'pve_role_del', roleid=roleid, **c)])
        kb.append([self.btn(uid, '« Роли', 'pve_roles', **c)])
        return self.screen(chat, mid, text[:4000], kb)

    def _privs_hint(self, uid, chat, mid, cid, cname):
        d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_roles', dict(cid=cid, cname=cname)))
        if d is None:
            return None
        return d.get('privileges') or []

    def cb_pve_role_new(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        privs = self._privs_hint(uid, chat, mid, cid, cname)
        if privs is None:
            return
        return self._ask(uid, chat, mid, {'kind': 'pve_role', 'c': c, 'privs': privs},
                         'Пришлите имя роли и привилегии через запятую, например\n'
                         '<code>VMPower VM.Audit,VM.PowerMgmt,VM.Console</code>\n\n'
                         f'Все привилегии кластера:\n<code>{v.e(", ".join(privs))[:3300]}</code>',
                         [[self.btn(uid, 'Отмена', 'pve_roles', **c)]])

    def cb_pve_role_edit(self, uid, chat, mid, cid, cname, roleid):
        c = dict(cid=cid, cname=cname)
        privs = self._privs_hint(uid, chat, mid, cid, cname)
        if privs is None:
            return
        return self._ask(uid, chat, mid, {'kind': 'pve_role', 'c': c, 'privs': privs, 'roleid': roleid},
                         f'Пришлите новый полный список привилегий роли <b>{v.e(roleid)}</b> через запятую. '
                         'Он заменит текущий.\n\n'
                         f'Все привилегии кластера:\n<code>{v.e(", ".join(privs))[:3300]}</code>',
                         [[self.btn(uid, 'Отмена', 'pve_role', roleid=roleid, **c)]])

    def cb_pve_role_del(self, uid, chat, mid, cid, cname, roleid, ok=False):
        c = dict(cid=cid, cname=cname)
        if not ok:
            kb = [[self.btn(uid, '✅ Да, удалить', 'pve_role_del', roleid=roleid, ok=True, **c),
                   self.btn(uid, 'Отмена', 'pve_role', roleid=roleid, **c)]]
            return self.screen(chat, mid, f'Удалить роль <b>{v.e(roleid)}</b>? Права, выданные с ней, пропадут.', kb)
        return self._do(uid, chat, mid, lambda a: a.delete_pve_role(cid, roleid),
                        f'Роль {v.e(roleid)} удалена', back=('pve_roles', c))

    # ------------------------------------------------------------------ ACL
    def cb_pve_acl(self, uid, chat, mid, cid, cname, page=0, subject=None):
        """All permissions, or those of one user/group (subject=(type, id)) to take some away."""
        c = dict(cid=cid, cname=cname)
        if subject:
            back = ('pve_user', dict(userid=subject[1], **c)) if subject[0] == 'user' \
                else ('pve_group', dict(groupid=subject[1], **c))
        else:
            back = ('pve', c)
        d = self._pve_load(uid, chat, mid, cid, cname, back=back)
        if d is None:
            return
        acl = [a for a in d.get('acl') or [] if not subject or (a.get('type'), a.get('ugid')) == tuple(subject)]
        pages = max(1, (len(acl) + APAGE - 1) // APAGE)
        page = min(max(0, page), pages - 1)
        chunk = acl[page * APAGE:(page + 1) * APAGE]
        start = page * APAGE + 1
        title = f'права {v.e(subject[1])}' if subject else 'права (ACL)'
        lines = [f'<b>{v.e(cname)}: {title}</b>, стр. {page + 1}/{pages}'] + (
            [f'{start + i}. {self._acl_line(a, who=not subject)}' for i, a in enumerate(chunk)] or ['Записей нет'])
        kb, row = [], []
        for i, a in enumerate(chunk):
            row.append(self.btn(uid, f'🗑 {start + i}', 'pve_acl_del', entry=a, subject=subject, **c))
            if len(row) == 4:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        nav = []
        if page > 0:
            nav.append(self.btn(uid, '‹', 'pve_acl', page=page - 1, subject=subject, **c))
        if page < pages - 1:
            nav.append(self.btn(uid, '›', 'pve_acl', page=page + 1, subject=subject, **c))
        if nav:
            kb.append(nav)
        grant = {'type': subject[0], 'ugid': subject[1]} if subject else {}
        kb.append([self.btn(uid, '➕ Выдать права', 'pve_grant', grant=grant, **c),
                   self.btn(uid, '« Назад', back[0], **back[1])])
        hint = '\n\nКнопка 🗑 N забирает запись N.' if chunk else ''
        return self.screen(chat, mid, '\n'.join(lines) + hint, kb)

    def cb_pve_acl_del(self, uid, chat, mid, cid, cname, entry, subject=None, ok=False):
        c = dict(cid=cid, cname=cname)
        if not ok:
            kb = [[self.btn(uid, '✅ Да, забрать', 'pve_acl_del', entry=entry, subject=subject, ok=True, **c),
                   self.btn(uid, 'Отмена', 'pve_acl', subject=subject, **c)]]
            return self.screen(chat, mid, f'Забрать права?\n{self._acl_line(entry)}', kb)
        kind = {'user': 'users', 'group': 'groups', 'token': 'tokens'}.get(entry.get('type'), 'users')
        return self._do(uid, chat, mid,
                        lambda a: a.set_pve_acl(cid, entry['path'], [entry['roleid']], delete=True,
                                                **{kind: [entry['ugid']]}),
                        f'Права забраны: {self._acl_line(entry)}', back=('pve_acl', dict(subject=subject, **c)))

    def cb_pve_grant(self, uid, chat, mid, cid, cname, grant):
        """Grant a role step by step: who, which role, where; then confirm."""
        c = dict(cid=cid, cname=cname)
        cancel = [self.btn(uid, 'Отмена', 'pve_acl', **c)]
        if not grant.get('ugid') or not grant.get('roleid'):
            d = self._pve_load(uid, chat, mid, cid, cname, back=('pve_acl', c))
            if d is None:
                return
        if not grant.get('ugid'):
            kb = [[self.btn(uid, f"👥 @{g['groupid']}"[:60], 'pve_grant', grant={'type': 'group', 'ugid': g['groupid']}, **c)]
                  for g in (d.get('groups') or [])[:20]]
            kb += [[self.btn(uid, f"👤 {u['userid']}"[:60], 'pve_grant', grant={'type': 'user', 'ugid': u['userid']}, **c)]
                   for u in (d.get('users') or [])[:30]]
            kb.append(cancel)
            return self.screen(chat, mid, 'Кому выдать права? Удобнее выдавать группе и добавлять в неё людей.', kb)
        who = f"{'группе @' if grant['type'] == 'group' else 'пользователю '}{grant['ugid']}"
        if not grant.get('roleid'):
            kb, row = [], []
            for r in d.get('roles') or []:
                row.append(self.btn(uid, r['roleid'][:40], 'pve_grant', grant=dict(grant, roleid=r['roleid']), **c))
                if len(row) == 2:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
            kb.append(cancel)
            return self.screen(chat, mid, f'Какую роль выдать {v.e(who)}?\n'
                                          'PVEVMUser: пользоваться VM, PVEVMAdmin: управлять VM, '
                                          'PVEAuditor: только смотреть, Administrator: всё.', kb)
        if not grant.get('path'):
            kb = [[self.btn(uid, f'{p} ({label})', 'pve_grant', grant=dict(grant, path=p), **c)] for p, label in PATHS]
            kb.append([self.btn(uid, '📦 Одна VM/CT', 'pve_grant_vm', grant=grant, **c),
                       self.btn(uid, '✏️ Ввести путь', 'pve_grant_path', grant=grant, **c)])
            kb.append(cancel)
            return self.screen(chat, mid, f'Где действует роль <b>{v.e(grant["roleid"])}</b> для {v.e(who)}?', kb)
        kb = [[self.btn(uid, '✅ Выдать', 'pve_grant_do', grant=grant, propagate=True, **c)],
              [self.btn(uid, '✅ Только на этот путь, без вложенных', 'pve_grant_do', grant=grant, propagate=False, **c)],
              cancel]
        return self.screen(chat, mid, f'Выдать роль <b>{v.e(grant["roleid"])}</b> {v.e(who)} '
                                      f'на <code>{v.e(grant["path"])}</code>?', kb)

    def cb_pve_grant_vm(self, uid, chat, mid, cid, cname, grant):
        c = dict(cid=cid, cname=cname)
        try:
            vms = self.api(uid).vms(cid)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, '« Назад', 'pve_grant', grant=grant, **c)]])
        kb = [[self.btn(uid, v.guest_button(x), 'pve_grant', grant=dict(grant, path=f"/vms/{int(x['vmid'])}"), **c)]
              for x in vms[:40]]
        kb.append([self.btn(uid, '« Назад', 'pve_grant', grant=grant, **c)])
        return self.screen(chat, mid, 'На какую VM/CT?', kb)

    def cb_pve_grant_path(self, uid, chat, mid, cid, cname, grant):
        c = dict(cid=cid, cname=cname)
        return self._ask(uid, chat, mid, {'kind': 'pve_acl_path', 'c': c, 'grant': grant},
                         'Пришлите путь, например <code>/vms/100</code>, <code>/storage/local</code>, '
                         '<code>/pool/dev</code>, <code>/nodes/pve</code>:',
                         [[self.btn(uid, 'Отмена', 'pve_grant', grant=grant, **c)]])

    def cb_pve_grant_do(self, uid, chat, mid, cid, cname, grant, propagate=True):
        c = dict(cid=cid, cname=cname)
        kind = 'groups' if grant['type'] == 'group' else 'users'
        back = ('pve_group', dict(groupid=grant['ugid'], **c)) if grant['type'] == 'group' \
            else ('pve_user', dict(userid=grant['ugid'], **c))
        return self._do(uid, chat, mid,
                        lambda a: a.set_pve_acl(cid, grant['path'], [grant['roleid']], propagate=propagate,
                                                **{kind: [grant['ugid']]}),
                        f"Роль {v.e(grant['roleid'])} выдана {v.e(grant['ugid'])} на {v.e(grant['path'])}", back=back)

    # ------------------------------------------------------------------ typed input
    def pve_input(self, msg, uid, chat, text, pend):
        kind = pend['kind']
        if kind == 'pve_userid':
            c = pend['c']
            userid = text.strip()
            if not USERID_RE.match(userid):
                self.pending[uid] = pend
                return self.tg.send(chat, 'Имя должно быть вида <code>имя@realm</code>, без пробелов, : и /. Ещё раз:')
            if userid.endswith('@pve'):
                return self._ask(uid, chat, None, {'kind': 'pve_newpass', 'c': c, 'userid': userid},
                                 f'Пароль для <b>{v.e(userid)}</b> (8–256 символов). Сообщение с паролем я сразу удалю.\n'
                                 'Можно без пароля и задать его позже.',
                                 [[self.btn(uid, 'Без пароля', 'pve_user_create', userid=userid, **c)],
                                  [self.btn(uid, 'Отмена', 'pve', **c)]])
            return self.cb_pve_user_create(uid, chat, None, userid=userid, **c)
        if kind in ('pve_newpass', 'pve_password'):
            self.tg.delete(chat, msg['message_id'])
            if msg['chat'].get('type') != 'private':
                return self.tg.send(chat, 'Пароль можно присылать только в личном чате с ботом. '
                                          'Если вы отправили его здесь, смените его.')
            if not 8 <= len(text) <= 256:
                self.pending[uid] = pend
                return self.tg.send(chat, 'Пароль: от 8 до 256 символов. Ещё раз:')
            if kind == 'pve_newpass':
                return self.cb_pve_user_create(uid, chat, None, userid=pend['userid'], password=text, **pend['c'])
            u = pend['u']
            return self._do(uid, chat, None, lambda a: a.set_pve_password(u['cid'], u['userid'], text),
                            f"Пароль {v.e(u['userid'])} изменён", back=('pve_user', u))
        if kind == 'pve_groupid':
            c = pend['c']
            groupid, _, comment = text.strip().partition(' ')
            if not ID_RE.match(groupid):
                self.pending[uid] = pend
                return self.tg.send(chat, 'Имя группы: латиница, цифры, точка, - и _. Ещё раз:')
            try:
                self.api(uid).create_pve_group(c['cid'], groupid, comment.strip())
            except ApiError as err:
                return self.error(chat, err, None, [[self.btn(uid, '« Группы', 'pve_groups', **c)]])
            return self.cb_pve_group(uid, chat, None, groupid=groupid, **c)
        if kind == 'pve_role':
            c = pend['c']
            roleid = pend.get('roleid')
            rest = text.strip()
            if not roleid:
                roleid, _, rest = rest.partition(' ')
                if not ID_RE.match(roleid):
                    self.pending[uid] = pend
                    return self.tg.send(chat, 'Имя роли: латиница, цифры, точка, - и _. Ещё раз:')
            privs = sorted({p for p in re.split(r'[\s,]+', rest) if p})
            known = set(pend.get('privs') or [])
            unknown = [p for p in privs if known and p not in known]
            if not privs or unknown:
                self.pending[uid] = pend
                why = f'Таких привилегий нет: <code>{v.e(", ".join(unknown))}</code>' if unknown else 'Нужна хотя бы одна привилегия.'
                return self.tg.send(chat, f'{why}\nЕщё раз:')
            try:
                if pend.get('roleid'):
                    self.api(uid).update_pve_role(c['cid'], roleid, privs)
                else:
                    self.api(uid).create_pve_role(c['cid'], roleid, privs)
            except ApiError as err:
                return self.error(chat, err, None, [[self.btn(uid, '« Роли', 'pve_roles', **c)]])
            return self.cb_pve_role(uid, chat, None, roleid=roleid, **c)
        if kind == 'pve_acl_path':
            path = text.strip()
            if not PATH_RE.match(path) or '..' in path.split('/'):
                self.pending[uid] = pend
                return self.tg.send(chat, 'Путь начинается с /, например <code>/vms/100</code>. Ещё раз:')
            return self.cb_pve_grant(uid, chat, None, grant=dict(pend['grant'], path=path), **pend['c'])
