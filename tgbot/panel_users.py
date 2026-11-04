# -*- coding: utf-8 -*-
"""PegaProx's own users (the accounts of the panel and the bot) from Telegram.

The screens call /api/users and /api/roles under the linked user's token, so PegaProx
applies its own checks: the admin.users permission, tenant limits, no role above your own,
no deleting yourself or the last admin. The bot only shows what PegaProx answers.
Passwords typed in chat are taken in private chats only and deleted right away.
"""
import re

from . import views as v
from .pegaprox_client import ApiError

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._@-]{2,63}$')
PPAGE = 10
HINT = ('Управлять пользователями PegaProx может тот, у кого есть право admin.users '
        '(обычно роль admin), и токен бота тоже должен иметь такую роль.')


class PanelUsersMixin:
    """Mixed into tgbot.bot.Bot: uses its btn, screen, error, _do, pending and api."""

    def _pp_fail(self, uid, chat, mid, err, back=('pp_users', {})):
        kb = [[self.btn(uid, '« Назад', back[0], **back[1])]]
        if err.status == 403:
            return self.screen(chat, mid, f'⛔ {HINT}\n\n{v.e(err.message)}', kb)
        return self.error(chat, err, mid, kb)

    # ------------------------------------------------------------------ hub
    def cmd_users(self, msg, uid, chat, arg):
        return self.cb_users(uid, chat, None)

    def cb_users(self, uid, chat, mid):
        """Both kinds of users: PegaProx's, and those of each Proxmox cluster."""
        kb = [[self.btn(uid, '🧑‍💻 Пользователи PegaProx', 'pp_users')]]
        try:
            clusters = self.api(uid).clusters()
        except ApiError:
            clusters = []
        kb += [[self.btn(uid, f'👤 Proxmox: {v.cluster_name(c)}'[:60], 'pve', cid=c['id'], cname=v.cluster_name(c))]
               for c in clusters]
        kb.append([self.btn(uid, '« Кластеры', 'clusters')])
        return self.screen(chat, mid, '<b>Пользователи</b>\n\n'
                                      '🧑‍💻 <b>PegaProx</b>: кто входит в эту панель и в бота, их роли.\n'
                                      '👤 <b>Proxmox</b>: пользователи самого кластера, группы, роли и права (ACL).', kb)

    # ------------------------------------------------------------------ list, card
    def _pp_find(self, uid, username):
        for u in self.api(uid).panel_users():
            if u.get('username') == username:
                return u
        return None

    def cb_pp_users(self, uid, chat, mid, page=0):
        try:
            users = sorted(self.api(uid).panel_users(), key=lambda u: u.get('username') or '')
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=('users', {}))
        pages = max(1, (len(users) + PPAGE - 1) // PPAGE)
        page = min(max(0, page), pages - 1)
        kb = [[self.btn(uid, f"{'🟢' if u.get('enabled', True) else '⚪'} {u['username']} ({u.get('role')})"[:60],
                        'pp_user', username=u['username'])] for u in users[page * PPAGE:(page + 1) * PPAGE]]
        nav = []
        if page > 0:
            nav.append(self.btn(uid, '‹', 'pp_users', page=page - 1))
        if page < pages - 1:
            nav.append(self.btn(uid, '›', 'pp_users', page=page + 1))
        if nav:
            kb.append(nav)
        kb.append([self.btn(uid, '➕ Создать', 'pp_new'), self.btn(uid, '« Назад', 'users')])
        return self.screen(chat, mid, f'<b>Пользователи PegaProx</b> ({len(users)}), стр. {page + 1}/{pages}\n'
                                      '🟢 включён, ⚪ выключен', kb)

    def cb_pp_user(self, uid, chat, mid, username):
        try:
            u = self._pp_find(uid, username)
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err)
        if not u:
            return self.screen(chat, mid, f'Пользователь {v.e(username)} не найден.',
                               [[self.btn(uid, '« Пользователи', 'pp_users')]])
        on = u.get('enabled', True)
        local = (u.get('auth_source') or 'local') == 'local'
        lines = [f"🧑‍💻 <b>{v.e(username)}</b>" + (f" ({v.e(u['display_name'])})"
                                                   if u.get('display_name') and u['display_name'] != username else ''),
                 f"Роль: <b>{v.e(u.get('role'))}</b>, тенант: {v.e(u.get('tenant_id'))}",
                 f"Состояние: {'🟢 включён' if on else '⚪ выключен'}",
                 f"Вход: {v.e(u.get('auth_source') or 'local')}, 2FA: {'да' if u.get('totp_enabled') else 'нет'}",
                 f"Последний вход: {v.when(u.get('last_login')) if u.get('last_login') else 'не входил'}"]
        if u.get('email'):
            lines.append(f"E-mail: {v.e(u['email'])}")
        if u.get('permissions'):
            lines.append(f"Доп. права: <code>{v.e(', '.join(u['permissions']))[:1500]}</code>")
        kb = [[self.btn(uid, '⚪ Выключить' if on else '🟢 Включить', 'pp_enable', username=username, on=not on),
               self.btn(uid, '🎭 Роль', 'pp_role', username=username)]]
        row = []
        if local:
            row.append(self.btn(uid, '🔐 Пароль', 'pp_pw', username=username))
        if u.get('totp_enabled'):
            row.append(self.btn(uid, '🔓 Сбросить 2FA', 'pp_2fa', username=username))
        if row:
            kb.append(row)
        kb.append([self.btn(uid, '🗑 Удалить', 'pp_del', username=username)])
        kb.append([self.btn(uid, '🔄 Обновить', 'pp_user', username=username), self.btn(uid, '« Пользователи', 'pp_users')])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    # ------------------------------------------------------------------ changes
    def cb_pp_enable(self, uid, chat, mid, username, on, ok=False):
        if not on and not ok:
            kb = [[self.btn(uid, '✅ Да, выключить', 'pp_enable', username=username, on=on, ok=True),
                   self.btn(uid, 'Отмена', 'pp_user', username=username)]]
            return self.screen(chat, mid, f'Выключить <b>{v.e(username)}</b>? Он не сможет войти в PegaProx '
                                          'и пользоваться ботом.', kb)
        try:
            self.api(uid).update_panel_user(username, {'enabled': bool(on)})
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=('pp_user', {'username': username}))
        return self.cb_pp_user(uid, chat, mid, username)

    def _roles_kb(self, uid, action, back, **ctx):
        roles = self.api(uid).panel_roles()
        kb, row = [], []
        for r in roles:
            row.append(self.btn(uid, f"{r.get('name') or r['id']}"[:40], action, role=r['id'], **ctx))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([self.btn(uid, 'Отмена', back[0], **back[1])])
        return kb

    def cb_pp_role(self, uid, chat, mid, username):
        back = ('pp_user', {'username': username})
        try:
            kb = self._roles_kb(uid, 'pp_role_set', back, username=username)
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=back)
        return self.screen(chat, mid, f'Новая роль для <b>{v.e(username)}</b>:\n'
                                      'admin: всё, user: управлять гостями, viewer: только смотреть.', kb)

    def cb_pp_role_set(self, uid, chat, mid, username, role):
        try:
            self.api(uid).update_panel_user(username, {'role': role})
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=('pp_user', {'username': username}))
        return self.cb_pp_user(uid, chat, mid, username)

    def cb_pp_pw(self, uid, chat, mid, username):
        self.pending[uid] = {'kind': 'pp_password', 'username': username}
        return self.screen(chat, mid, f'Пришлите новый пароль для <b>{v.e(username)}</b>.\n'
                                      'Только в личном чате: сообщение с паролем я сразу удалю. '
                                      'Все сеансы пользователя будут закрыты.',
                           [[self.btn(uid, 'Отмена', 'pp_user', username=username)]])

    def cb_pp_2fa(self, uid, chat, mid, username, ok=False):
        if not ok:
            kb = [[self.btn(uid, '✅ Да, сбросить', 'pp_2fa', username=username, ok=True),
                   self.btn(uid, 'Отмена', 'pp_user', username=username)]]
            return self.screen(chat, mid, f'Сбросить двухфакторную защиту у <b>{v.e(username)}</b>? '
                                          'Он войдёт только по паролю, пока не настроит её снова.', kb)
        return self._do(uid, chat, mid, lambda a: a.reset_panel_2fa(username),
                        f'2FA у {v.e(username)} сброшена', back=('pp_user', {'username': username}))

    def cb_pp_del(self, uid, chat, mid, username, ok=False):
        if not ok:
            kb = [[self.btn(uid, '✅ Да, удалить', 'pp_del', username=username, ok=True),
                   self.btn(uid, 'Отмена', 'pp_user', username=username)]]
            return self.screen(chat, mid, f'Удалить пользователя PegaProx <b>{v.e(username)}</b>? '
                                          'Его API-токены тоже перестанут работать. Это не отменить.', kb)
        return self._do(uid, chat, mid, lambda a: a.delete_panel_user(username),
                        f'Пользователь {v.e(username)} удалён', back=('pp_users', {}))

    # ------------------------------------------------------------------ new user
    def cb_pp_new(self, uid, chat, mid):
        self.pending[uid] = {'kind': 'pp_username'}
        return self.screen(chat, mid, '<b>Новый пользователь PegaProx</b>\nПришлите логин '
                                      '(латиница, цифры, точка, -, _; от 3 символов):',
                           [[self.btn(uid, 'Отмена', 'pp_users')]])

    def cb_pp_new_role(self, uid, chat, mid, username, role):
        self.pending[uid] = {'kind': 'pp_newpass', 'username': username, 'role': role}
        return self.screen(chat, mid, f'Пароль для <b>{v.e(username)}</b> (роль {v.e(role)}).\n'
                                      'По умолчанию PegaProx требует от 8 символов, заглавную, строчную букву и цифру. '
                                      'Сообщение с паролем я сразу удалю.',
                           [[self.btn(uid, 'Отмена', 'pp_users')]])

    # ------------------------------------------------------------------ typed input
    def pp_input(self, msg, uid, chat, text, pend):
        kind = pend['kind']
        if kind == 'pp_username':
            name = text.strip().lower()
            if not NAME_RE.match(name):
                self.pending[uid] = pend
                return self.tg.send(chat, 'Логин: латиница, цифры, точка, - и _, от 3 до 64 символов. Ещё раз:')
            try:
                kb = self._roles_kb(uid, 'pp_new_role', ('pp_users', {}), username=name)
            except ApiError as err:
                return self._pp_fail(uid, chat, None, err)
            return self.tg.send(chat, f'Какая роль будет у <b>{v.e(name)}</b>?', kb)
        # a password: never leave it in the chat
        self.tg.delete(chat, msg['message_id'])
        if msg['chat'].get('type') != 'private':
            return self.tg.send(chat, 'Пароль можно присылать только в личном чате с ботом. '
                                      'Если вы отправили его здесь, смените его.')
        username = pend['username']
        if kind == 'pp_newpass':
            try:
                self.api(uid).create_panel_user(username, text, pend['role'])
            except ApiError as err:
                if err.status == 400 and 'password' in err.message.lower():
                    self.pending[uid] = pend
                    return self.tg.send(chat, f'❌ {v.e(err.message)}\nПришлите другой пароль:')
                return self._pp_fail(uid, chat, None, err)
            self.tg.send(chat, f'✅ Пользователь PegaProx <b>{v.e(username)}</b> создан.')
            return self.cb_pp_user(uid, chat, None, username)
        if kind == 'pp_password':
            back = ('pp_user', {'username': username})
            try:
                self.api(uid).set_panel_password(username, text)
            except ApiError as err:
                if err.status == 400:
                    self.pending[uid] = pend
                    return self.tg.send(chat, f'❌ {v.e(err.message)}\nПришлите другой пароль:')
                return self._pp_fail(uid, chat, None, err, back=back)
            return self.tg.send(chat, f'✅ Пароль {v.e(username)} изменён.',
                                [[self.btn(uid, '« Назад', back[0], **back[1])]])
