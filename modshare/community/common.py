import functools
import ipaddress
import json
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import RequestDataTooBig, SuspiciousOperation
from django.db import OperationalError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import Throttle


class ApiError(Exception):
    def __init__(self, message, code='invalid_request', status=400, fields=None):
        self.message, self.code, self.status, self.fields = message, code, status, fields or {}


def success(data=None, status=200):
    return JsonResponse({'ok': True, 'data': data if data is not None else {}}, status=status)


def error_response(error):
    return JsonResponse({'ok': False, 'error': {'code': error.code, 'message': error.message, 'fields': error.fields}}, status=error.status)


def endpoint(methods=('GET',), access='public'):
    def wrap(function):
        @functools.wraps(function)
        def run(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    raise ApiError('不支持这个请求方式。', 'method_not_allowed', 405)
                if access != 'public':
                    if not request.user.is_authenticated:
                        raise ApiError('请先登录。', 'login_required', 401)
                    if access in ('active', 'admin', 'owner') and request.user.banned_at:
                        raise ApiError('账号已被封禁，无法执行此操作。', 'account_banned', 403)
                    if access in ('admin', 'owner') and request.user.role not in ('admin', 'owner'):
                        raise ApiError('你没有管理权限。', 'forbidden', 403)
                    if access == 'owner' and request.user.role != 'owner':
                        raise ApiError('仅超级管理员可以执行此操作。', 'forbidden', 403)
                return function(request, *args, **kwargs)
            except ApiError as exc:
                return error_response(exc)
            except (json.JSONDecodeError, UnicodeDecodeError, RequestDataTooBig, SuspiciousOperation):
                return error_response(ApiError('请求内容不符合要求。'))
            except OperationalError:
                return error_response(ApiError('服务正忙，请稍后重试。', 'service_busy', 503))
        return run
    return wrap


def json_body(request):
    if request.content_type != 'application/json':
        raise ApiError('请使用 JSON 提交表单。')
    result = json.loads(request.body)
    if not isinstance(result, dict):
        raise ApiError('表单格式错误。')
    return result


def text_value(data, key, maximum=500, required=False):
    value = data.get(key, '')
    if not isinstance(value, str):
        raise ApiError('表单字段格式错误。', fields={key: '请输入文字。'})
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ApiError('请检查填写内容。', fields={key: f'请填写 1–{maximum} 个字符。'})
    return value


def client_ip(request):
    address = request.META.get('REMOTE_ADDR', '')
    if address in ('127.0.0.1', '::1') and settings.CONFIG.get('secure'):
        address = request.META.get('HTTP_X_REAL_IP', address)
    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        return 'unknown'


def throttle(name, identifier, limit, seconds):
    key = salted_hmac('modshare.throttle', f'{name}:{identifier}', algorithm='sha256').hexdigest()
    now = timezone.now()
    with transaction.atomic():
        record, _ = Throttle.objects.get_or_create(key=key, defaults={'started_at': now})
        if now >= record.started_at + timedelta(seconds=seconds):
            record.started_at, record.count = now, 0
        if record.count >= limit:
            raise ApiError('操作过于频繁，请稍后重试。', 'rate_limited', 429)
        record.count += 1
        record.save(update_fields=['started_at', 'count'])


def display_label(user):
    suffix={'owner':'站长','admin':'管理员'}.get(user.role)
    return f'{user.display_name}（{suffix}）' if suffix else user.display_name


def user_data(user):
    return {'id': user.id, 'email': user.email, 'display_name': user.display_name,
            'display_label':display_label(user),
            'role': user.role, 'banned': bool(user.banned_at), 'ban_reason': user.ban_reason}


def csrf_failure(request, reason=''):
    return error_response(ApiError('页面会话已过期，请刷新后重试。', 'csrf_failed', 403))


class ResponseHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Cache-Control', 'no-store')
        response['X-Content-Type-Options'] = 'nosniff'
        response.setdefault('Referrer-Policy', 'same-origin')
        response['X-Frame-Options'] = 'DENY'
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if settings.TURNSTILE_ENABLED and request.path_info in ('/login/', '/register/', '/reset-password/'):
            response['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self' data:; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response
