"""Validation and read-only Gmail PIN retrieval. No browser dependencies."""
import email
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
import imaplib
import re
import ssl
import time
from datetime import datetime, timezone
from decimal import Decimal


class StopRenewal(RuntimeError):
    pass


def require_free_offer(text):
    text = ' '.join(text.split())
    if not re.search(r'vServer\s+VS2-free\s+v2\.1\b', text, re.I):
        raise StopRenewal('原套餐名称不匹配，停止续期。')
    for label in (r'One-time extension fee', r'per month'):
        match = re.search(label + r'\s*:\s*(\d+[.,]\d{2})\s*EUR\b', text, re.I)
        if not match or Decimal(match[1].replace(',', '.')) != 0:
            raise StopRenewal('不能确认续期费和月费均为零，停止续期。')
    prices = re.findall(r'([\d.,]+)\s*EUR\b', text, re.I)
    if len(prices) != 2 or any(Decimal(p.replace(',', '.')) != 0 for p in prices):
        raise StopRenewal('套餐费用结构变化，停止续期。')


def extract_pin(raw, sender, requested_at):
    msg = email.message_from_bytes(raw, policy=policy.default)
    if parseaddr(str(msg.get('From', '')))[1].lower() != sender.lower():
        return None
    try:
        sent = parsedate_to_datetime(str(msg['Date']))
        if sent.tzinfo is None or sent.timestamp() < requested_at - 5:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    parts = []
    for part in msg.walk():
        if part.get_content_disposition() == 'attachment':
            continue
        if part.get_content_type() not in ('text/plain', 'text/html'):
            continue
        content = part.get_content()
        if part.get_content_type() == 'text/html':
            content = unescape(re.sub(r'<[^>]+>', ' ', content))
        parts.append(content)
    body = '\n'.join(parts)
    if not re.search(r'confirmation of a security check at EUserv', body, re.I):
        return None
    pins = set(re.findall(r'\bPIN\s*:\s*([0-9]{6})(?![0-9])', body, re.I))
    if len(pins) != 1:
        return None
    return pins.pop()


class Mailbox:
    def __init__(self, address, password, sender):
        self.address, self.password, self.sender = address, password, sender
        self.client = None

    def __enter__(self):
        self.client = imaplib.IMAP4_SSL('imap.gmail.com', ssl_context=ssl.create_default_context(), timeout=30)
        try:
            self.client.login(self.address, self.password.replace(' ', ''))
            status, _ = self.client.select('INBOX', readonly=True)
            if status != 'OK':
                raise StopRenewal('无法读取 Gmail 收件箱。')
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.client:
            try:
                self.client.logout()
            except Exception:
                pass

    def checkpoint(self):
        status, data = self.client.status('INBOX', '(UIDVALIDITY UIDNEXT)')
        if status != 'OK':
            raise StopRenewal('无法建立邮箱新邮件检查点。')
        value = data[0].decode()
        validity = re.search(r'UIDVALIDITY (\d+)', value)
        next_uid = re.search(r'UIDNEXT (\d+)', value)
        if not validity or not next_uid:
            raise StopRenewal('邮箱未返回 UID 检查点。')
        return int(validity[1]), int(next_uid[1])

    def wait_pin(self, checkpoint, requested_at, timeout=180):
        validity, first_uid = checkpoint
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.client.noop()
            if self.checkpoint()[0] != validity:
                raise StopRenewal('邮箱 UID 已变化，停止读取以防使用旧 PIN。')
            status, data = self.client.uid('search', None, 'UID', f'{first_uid}:*')
            if status != 'OK':
                raise StopRenewal('搜索新邮件失败。')
            candidates = []
            for uid in data[0].split():
                # IMAP n:* can include the latest older message when n exceeds max UID.
                if int(uid) < first_uid:
                    continue
                status, records = self.client.uid('fetch', uid, '(BODY.PEEK[])')
                if status != 'OK':
                    raise StopRenewal('读取新邮件失败。')
                for record in records:
                    if isinstance(record, tuple):
                        pin = extract_pin(record[1], self.sender, requested_at)
                        if pin:
                            candidates.append(pin)
            if len(candidates) > 1:
                raise StopRenewal('收到多封新 PIN 邮件，不能确认所属会话。请避免同时手动续期。')
            if candidates:
                return candidates[0]
            time.sleep(10)
        raise StopRenewal('等待本次 PIN 超时；请检查发件人配置、垃圾箱和邮箱连接。')


def report(message):
    import os
    print(message)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as out:
            out.write(message + '\n')
