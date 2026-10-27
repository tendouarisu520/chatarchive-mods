import secrets
from datetime import timedelta
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from .common import ApiError, client_ip, endpoint, json_body, success, text_value, throttle, user_data
from .models import EmailChallenge, User
from .turnstile import verify as verify_turnstile


def email_value(body):
    email = text_value(body, 'email', 254, True).casefold()
    try:
        validate_email(email)
    except ValidationError:
        raise ApiError('请填写有效的邮箱地址。', fields={'email': '邮箱地址格式错误。'})
    return email


def password_value(body):
    password = body.get('password')
    if not isinstance(password, str) or len(password) > 128 or password != body.get('confirm'):
        raise ApiError('两次密码须一致，且不能超过 128 个字符。', fields={'password': '请检查两次密码。'})
    try:
        validate_password(password)
    except ValidationError:
        raise ApiError('密码至少 10 位，且不能是常见密码或纯数字。', fields={'password': '请使用更强的密码。'})
    return password


def code_digest(email, purpose, code):
    return salted_hmac('modshare.email.code', f'{email}:{purpose}:{code}', algorithm='sha256').hexdigest()


def verification_locked(email, purpose, supplied):
    challenge = EmailChallenge.objects.filter(email=email, purpose=purpose).first()
    if not challenge or challenge.expires_at <= timezone.now():
        return None, ApiError('验证码无效或已过期，请重新发送。', 'invalid_code')
    if challenge.attempts >= 5:
        return None, ApiError('验证码错误次数过多，请重新发送。', 'code_attempts_exceeded', 429)
    valid = isinstance(supplied, str) and len(supplied) == 6 and supplied.isascii() and supplied.isdigit()
    if not valid or not constant_time_compare(challenge.code_hash, code_digest(email, purpose, supplied)):
        challenge.attempts += 1
        challenge.save(update_fields=['attempts'])
        return None, ApiError('验证码不正确。', 'invalid_code')
    return challenge, None


@endpoint()
def me(request):
    get_token(request)
    from .resources import quota_data
    return success({'user': user_data(request.user) if request.user.is_authenticated else None,
                    'quota': quota_data(request.user) if request.user.is_authenticated else None,
                    'limits': {'max_file_bytes': 50_000_000, 'max_preview_bytes': 2_000_000}})


@endpoint(('POST',))
def send_code(request):
    body = json_body(request)
    email = email_value(body)
    purpose = body.get('purpose', 'register')
    if purpose not in ('register', 'reset'):
        raise ApiError('验证码用途无效。')
    throttle('mail-ip', client_ip(request), 15, 3600)
    throttle('mail-address', email, 5, 3600)
    verify_turnstile(body, 'register' if purpose == 'register' else 'reset_password')
    existing = User.objects.filter(email=email).exists()
    message = '如果该邮箱符合要求，验证码将发送到收件箱，10 分钟内有效。'
    if (purpose == 'register' and existing) or (purpose == 'reset' and not existing):
        return success({'message': message})
    now, code = timezone.now(), f'{secrets.randbelow(1_000_000):06d}'
    digest = code_digest(email, purpose, code)
    with transaction.atomic():
        previous = EmailChallenge.objects.filter(email=email, purpose=purpose).first()
        if previous and now < previous.sent_at + timedelta(seconds=60):
            raise ApiError('请等待 60 秒后重新发送。', 'resend_cooldown', 429)
        challenge, _ = EmailChallenge.objects.update_or_create(email=email, purpose=purpose, defaults={
            'code_hash': digest, 'sent_at': now, 'expires_at': now + timedelta(minutes=10), 'attempts': 0})
    try:
        purpose_name = '注册' if purpose == 'register' else '重设密码'
        send_mail(f'ChatArchive 模组分享站 · {purpose_name}验证码',
                  f'你的{purpose_name}验证码是：{code}\n\n验证码 10 分钟内有效，只能使用一次。\n如非本人操作，请忽略此邮件。\n\nChatArchive 模组分享站',
                  None, [email], fail_silently=False)
    except Exception:
        EmailChallenge.objects.filter(pk=challenge.pk, code_hash=digest).delete()
        raise ApiError('邮件暂时发送失败，请稍后重试。', 'email_unavailable', 503)
    return success({'message': message})


@endpoint(('POST',))
def register(request):
    body = json_body(request)
    email, password = email_value(body), password_value(body)
    name = text_value(body, 'display_name', 40) or '旅人'
    throttle('register-ip', client_ip(request), 30, 3600)
    verify_turnstile(body, 'register')
    failure, user = None, None
    try:
        with transaction.atomic():
            if User.objects.filter(email=email).exists():
                raise ApiError('这个邮箱已注册，请直接登录。', 'email_exists', 409)
            challenge, failure = verification_locked(email, 'register', body.get('code'))
            if not failure:
                user = User.objects.create_user(email=email, password=password, display_name=name)
                challenge.delete()
    except IntegrityError:
        raise ApiError('这个邮箱已注册，请直接登录。', 'email_exists', 409)
    if failure:
        raise failure
    login(request, user)
    return success({'user': user_data(user), 'message': '账号已创建。'}, 201)


@endpoint(('POST',))
def sign_in(request):
    body = json_body(request)
    email = email_value(body)
    password = body.get('password', '')
    if not isinstance(password, str) or len(password) > 128:
        raise ApiError('邮箱或密码不正确。', 'invalid_credentials', 401)
    throttle('login-ip', client_ip(request), 40, 900)
    throttle('login-account', email, 15, 900)
    verify_turnstile(body, 'login')
    account = User.objects.filter(email=email).first()
    # authenticate also hashes a dummy password when the account is absent.
    user = authenticate(request, username=account.username if account else email, password=password)
    if not user:
        raise ApiError('邮箱或密码不正确。', 'invalid_credentials', 401)
    login(request, user)
    return success({'user': user_data(user)})


@endpoint(('POST',))
def sign_out(request):
    logout(request)
    return success({'message': '已退出登录。'})


@endpoint(('POST',))
def reset_password(request):
    body = json_body(request)
    email, password = email_value(body), password_value(body)
    throttle('reset-ip', client_ip(request), 30, 3600)
    verify_turnstile(body, 'reset_password')
    failure = None
    with transaction.atomic():
        challenge, failure = verification_locked(email, 'reset', body.get('code'))
        account = User.objects.filter(email=email).first()
        if not account:
            failure = ApiError('验证码无效或已过期。', 'invalid_code')
        if not failure:
            account.set_password(password)
            account.save(update_fields=['password'])
            challenge.delete()
    if failure:
        raise failure
    logout(request)
    return success({'message': '密码已更新，请重新登录。'})
