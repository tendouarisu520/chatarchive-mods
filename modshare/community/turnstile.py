"""Validate single-use Cloudflare tokens for this site's account operations."""
import json
import logging
import re
import urllib.error
import urllib.request
from django.conf import settings
from .common import ApiError, client_ip, endpoint, json_body, success, throttle

SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
logger = logging.getLogger(__name__)


@endpoint(('POST',))
def report(request):
    body=json_body(request)
    code=body.get('code'); action=body.get('action')
    if action not in ('register','login','reset_password') or not isinstance(code,str) or not re.fullmatch(r'(?:\d{6}|script-load-failed)',code):
        raise ApiError('验证故障报告格式无效。')
    throttle('turnstile-report',client_ip(request),10,60)
    logger.warning('Turnstile client failure action=%s code=%s',action,code)
    return success()


def verify(body, action):
    if not settings.TURNSTILE_ENABLED:
        return
    token = body.get('turnstile_token')
    if not isinstance(token, str) or not token.strip() or len(token) > 2048:
        raise ApiError('请先完成人机验证。', 'human_verification_required', 403)
    request = urllib.request.Request(SITEVERIFY_URL,
        data=json.dumps({'secret':settings.TURNSTILE_SECRET_KEY, 'response':token}).encode(),
        headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError('Unexpected verification response size')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Unexpected verification response shape')
    except (urllib.error.URLError, OSError, ValueError):
        logger.warning('Turnstile unavailable action=%s', action)
        raise ApiError('人机验证服务暂时无法连接，请稍后重试。', 'human_verification_unavailable', 503) from None
    if (result.get('success') is not True or result.get('hostname') not in settings.TURNSTILE_HOSTNAMES
            or result.get('action') != action):
        raw_codes=result.get('error-codes', [])
        codes=[c for c in raw_codes[:5] if isinstance(c,str) and re.fullmatch(r'[a-z-]{1,50}',c)] if isinstance(raw_codes,list) else []
        logger.warning('Turnstile rejected action=%s codes=%s hostname_matches=%s action_matches=%s',
            action, ','.join(codes) or 'none', result.get('hostname') in settings.TURNSTILE_HOSTNAMES, result.get('action')==action)
        raise ApiError('人机验证未通过或已过期，请重新验证后重试。', 'human_verification_failed', 403)
