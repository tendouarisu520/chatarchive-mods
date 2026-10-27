from django.utils import timezone
from django.db import transaction
from .common import ApiError, display_label, endpoint, json_body, success, text_value, user_data
from .models import Audit, User


@endpoint(access='admin')
def users(request):
    query = request.GET.get('q', '').strip()[:254]
    accounts = User.objects.all().order_by('-date_joined')
    if query:
        from django.db.models import Q
        accounts = accounts.filter(Q(email__icontains=query) | Q(display_name__icontains=query))
    from .resources import paginate
    return success(paginate(accounts, request, account_data))


def account_data(account):
    result = user_data(account)
    result.update(date_joined=account.date_joined.isoformat(), upload_count=account.resources.count())
    return result


@endpoint(('GET', 'POST'), access='admin')
def user_detail(request, user_id):
    target = User.objects.filter(pk=user_id).first()
    if not target:
        raise ApiError('账户不存在。', 'not_found', 404)
    if request.method == 'GET':
        from .resources import paginate, resource_data
        listing = paginate(target.resources.select_related('author').order_by('-created_at', '-id'),
                           request, lambda r: resource_data(r, private=True))
        return success({'user': account_data(target), 'resources': listing.pop('items'),
                        'resource_pagination': {**listing, 'page_size': 24}})
    body = json_body(request)
    action, reason = body.get('action'), text_value(body, 'reason', 500)
    if action not in ('ban', 'unban', 'promote', 'demote'):
        raise ApiError('无效的账户操作。')
    with transaction.atomic():
        actor = User.objects.get(pk=request.user.pk)
        target = User.objects.get(pk=user_id)
        if actor.banned_at or actor.role not in ('admin', 'owner'):
            raise ApiError('管理权限已变更，请刷新页面。', 'forbidden', 403)
        if target.role == 'owner':
            raise ApiError('超级管理员账户受到保护。', 'owner_protected', 403)
        if action in ('promote', 'demote') and actor.role != 'owner':
            raise ApiError('只有超级管理员可以任免管理员。', 'forbidden', 403)
        if action in ('ban', 'unban') and target.role == 'admin' and actor.role != 'owner':
            raise ApiError('只有超级管理员可以管理管理员账户。', 'forbidden', 403)
        if action == 'ban':
            if not reason:
                raise ApiError('封禁时请填写原因。', fields={'reason': '请填写封禁原因。'})
            target.banned_at, target.ban_reason = timezone.now(), reason
        elif action == 'unban':
            target.banned_at, target.ban_reason = None, ''
        else:
            target.role = 'admin' if action == 'promote' else 'user'
        target.save(update_fields=['banned_at', 'ban_reason', 'role'])
        Audit.objects.create(actor=actor, action=action, target=f'user:{target.id}', reason=reason)
    return success({'user': user_data(target)})


@endpoint(access='admin')
def audit_log(request):
    return success({'items': [{'actor': display_label(a.actor), 'action': a.action, 'target': a.target,
                               'reason': a.reason, 'created_at': a.created_at.isoformat()}
                              for a in Audit.objects.select_related('actor')[:200]]})
