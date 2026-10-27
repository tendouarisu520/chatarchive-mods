"""Short-lived, per-file download authorization for native mobile downloaders."""
from urllib.parse import urlencode
from django.core import signing
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from .common import ApiError, endpoint, json_body, success, throttle
from .models import Revision, User

TICKET_SECONDS = 900
TICKET_SALT = 'modshare.download.v1'


def checked_revision(actor, revision_id, review=False):
    revision = Revision.objects.select_related('blob', 'resource').filter(pk=revision_id).first()
    if not revision:
        raise ApiError('文件不存在。', 'not_found', 404)
    resource = revision.resource
    public = resource.state == 'published' and resource.published_revision_id == revision.id
    private = actor.pk == resource.author_id or actor.role in ('admin', 'owner')
    if (review and not private) or (not public and not private):
        raise ApiError('文件不存在或你没有审阅权限。', 'not_found', 404)
    return revision, public


def download_actor(request, revision_id, review=False):
    from .resources import actor_locked
    ticket = request.GET.get('ticket')
    if ticket is None:
        if not request.user.is_authenticated:
            raise ApiError('请先登录。', 'login_required', 401)
        return actor_locked(request)
    try:
        if not ticket or len(ticket) > 2048:
            raise signing.BadSignature()
        data = signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_SECONDS)
        if (not isinstance(data, dict) or type(data.get('user')) is not int
                or data.get('revision') != str(revision_id) or data.get('review') is not review
                or not isinstance(data.get('auth'), str)):
            raise signing.BadSignature()
        actor = User.objects.filter(pk=data['user']).first()
        if not actor or not constant_time_compare(actor.get_session_auth_hash(), data['auth']):
            raise signing.BadSignature()
    except signing.SignatureExpired:
        raise ApiError('下载链接已过期，请回到作品页重新点击下载。', 'download_link_expired', 410)
    except (signing.BadSignature, ValueError, TypeError):
        raise ApiError('下载链接无效，请回到作品页重新点击下载。', 'download_link_invalid', 403)
    if request.user.is_authenticated and request.user.pk != actor.pk:
        raise ApiError('下载链接与当前登录账号不一致。', 'download_account_mismatch', 403)
    if actor.banned_at:
        raise ApiError('账号已被封禁，无法下载。', 'account_banned', 403)
    return actor


@endpoint(('POST',), access='active')
def issue(request, revision_id):
    from .resources import actor_locked
    body = json_body(request)
    review = body.get('review', False)
    if type(review) is not bool:
        raise ApiError('下载类型无效。')
    actor = actor_locked(request)
    checked_revision(actor, revision_id, review)
    throttle('download-ticket-user', str(actor.pk), 60, 60)
    ticket = signing.dumps({'user':actor.pk, 'revision':str(revision_id), 'review':review,
                            'auth':actor.get_session_auth_hash()}, salt=TICKET_SALT, compress=True)
    path = reverse('review-download' if review else 'download', args=[revision_id])
    return success({'url':path+'?'+urlencode({'ticket':ticket}), 'expires_in':TICKET_SECONDS})
