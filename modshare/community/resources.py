from datetime import datetime, time, timedelta
from pathlib import Path
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from .common import ApiError, display_label, endpoint, json_body, success, text_value, throttle
from .models import Audit, Blob, DailyUpload, Resource, Revision, StorageUsage, User
from .uploads import prepare_file
from .previews import prepare_preview, preview_data
from .engagement import counts, record_download, with_counts


def quota_data(user):
    day = timezone.localdate(timezone.now())
    count = DailyUpload.objects.filter(user=user, day=day).values_list('count', flat=True).first() or 0
    reset = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
    return {'used': count, 'limit': settings.DAILY_UPLOAD_LIMIT, 'remaining': max(0, settings.DAILY_UPLOAD_LIMIT - count), 'resets_at': reset.isoformat()}


def paginate(queryset, request, serializer):
    paginator = Paginator(queryset, 24)
    page = paginator.get_page(request.GET.get('page', 1))
    return {'items': [serializer(item) for item in page], 'total': paginator.count,
            'page': page.number, 'pages': paginator.num_pages}


def file_data(revision):
    blob = revision.blob
    return {'id': str(revision.id), 'revision_id': str(revision.id), 'name': blob.original_name,
            'size': blob.size, 'extension': blob.extension, 'sha256': blob.sha256}


def revision_data(revision):
    return {'id': str(revision.id), 'resource_id': str(revision.resource_id), 'title': revision.title,
            'description': revision.description, 'status': revision.status, 'reason': revision.reason,
            'file': file_data(revision), 'preview': preview_data(revision), 'created_at': revision.created_at.isoformat(),
            'reviewed_at': revision.reviewed_at.isoformat() if revision.reviewed_at else None}


def resource_data(resource, private=False):
    latest = resource.revisions.select_related('blob', 'preview').first() if private else None
    revision = latest if private else resource.published_revision
    result = {'id': str(resource.id), 'category': resource.category, 'title': revision.title,
              'description': revision.description, 'author': {'id': resource.author_id, 'name': display_label(resource.author)},
              'status': resource.state, 'created_at': resource.created_at.isoformat(),
              'published_at': resource.published_at.isoformat() if resource.published_at else None,
              'published_revision_id': str(resource.published_revision_id) if resource.published_revision_id else None,
              'file': file_data(revision), 'preview': preview_data(revision), 'latest_revision': None}
    if private:
        result['latest_revision'] = revision_data(latest)
        result['unpublish_reason'] = resource.unpublish_reason
    result.update(counts(resource))
    return result


def actor_locked(request, admin=False):
    actor = User.objects.get(pk=request.user.pk)
    if actor.banned_at:
        raise ApiError('账号已被封禁，无法上传或下载。', 'account_banned', 403)
    if admin and actor.role not in ('admin', 'owner'):
        raise ApiError('管理权限已变更，请刷新页面。', 'forbidden', 403)
    return actor


def store_blobs_and_quota(actor, prepared_items):
    day = timezone.localdate(timezone.now())
    quota, _ = DailyUpload.objects.get_or_create(user=actor, day=day)
    if quota.count >= settings.DAILY_UPLOAD_LIMIT:
        raise ApiError('今日已成功上传 5 次，请明天再来。', 'daily_limit', 429)
    storage, _ = StorageUsage.objects.get_or_create(pk=1)
    total = sum(prepared['size'] for prepared in prepared_items)
    if storage.bytes + total > settings.MAX_STORAGE_BYTES:
        raise ApiError('站点存储空间已满，请联系管理员。', 'storage_full', 507)
    blobs = [Blob.objects.create(**prepared) for prepared in prepared_items]
    DailyUpload.objects.filter(pk=quota.pk).update(count=F('count') + 1)
    StorageUsage.objects.filter(pk=1).update(bytes=F('bytes') + total)
    return blobs


def cleanup_prepared(items):
    for prepared in items:
        (settings.PRIVATE_ROOT / prepared['storage_name']).unlink(missing_ok=True)


def read_submission(request, require_file=True):
    body = request.POST
    if getattr(request, 'mod_preview_excess', False):
        raise ApiError('例图不能超过 2MB（2,000,000 字节）。', 'preview_too_large', 413, {'preview': '请选择 2MB 以内的图片。'})
    if getattr(request, 'mod_file_excess', False):
        raise ApiError('文件超过 50MB 上限。', 'file_too_large', 413)
    title = text_value(body, 'title', 120, True)
    description = text_value(body, 'description', 20000, True)
    uploaded = request.FILES.get('file')
    if require_file and not uploaded:
        raise ApiError('请选择要上传的文件。', fields={'file': '文件不能为空。'})
    if set(request.FILES) - {'file', 'preview'} or any(len(request.FILES.getlist(name)) != 1 for name in request.FILES):
        raise ApiError('每次只能提交一个资源文件和一张例图。')
    picture = request.FILES.get('preview')
    remove = body.get('remove_preview', '')
    if remove not in ('', '0', '1') or (picture and remove == '1'):
        raise ApiError('不能同时上传和删除例图。', fields={'preview': '请选择替换或删除其中一种操作。'})
    return title, description, uploaded, picture, remove == '1'


@endpoint(('POST',), access='active')
def upload(request):
    throttle('upload-user', str(request.user.pk), 30, 3600)
    title, description, uploaded, picture, remove = read_submission(request)
    category = request.POST.get('category')
    if quota_data(request.user)['remaining'] <= 0:
        raise ApiError('今日已成功上传 5 次，请明天再来。', 'daily_limit', 429)
    prepared = []
    try:
        prepared.append(prepare_file(uploaded, category))
        if picture:
            prepared.append(prepare_preview(picture))
        with transaction.atomic():
            actor = actor_locked(request)
            blobs = store_blobs_and_quota(actor, prepared)
            resource = Resource.objects.create(author=actor, category=category)
            Revision.objects.create(resource=resource, title=title, description=description,
                                    blob=blobs[0], preview=blobs[1] if picture else None)
            Audit.objects.create(actor=actor, action='submit', target=f'resource:{resource.id}')
    except BaseException:
        cleanup_prepared(prepared)
        raise
    return success(resource_data(resource, private=True), 201)


@endpoint(('POST',), access='active')
def revise(request, resource_id):
    resource = Resource.objects.filter(pk=resource_id, author=request.user).first()
    if not resource:
        raise ApiError('投稿不存在。', 'not_found', 404)
    throttle('revise-user', str(request.user.pk), 30, 3600)
    title, description, uploaded, picture, remove = read_submission(request, require_file=False)
    if (uploaded or picture) and quota_data(request.user)['remaining'] <= 0:
        raise ApiError('今日已成功上传 5 次，请明天再来。', 'daily_limit', 429)
    prepared = []
    try:
        if uploaded:
            prepared.append(prepare_file(uploaded, resource.category))
        if picture:
            prepared.append(prepare_preview(picture))
        with transaction.atomic():
            actor = actor_locked(request)
            resource = Resource.objects.get(pk=resource_id, author=request.user)
            previous = resource.revisions.select_related('blob', 'preview').first()
            if prepared:
                blobs = store_blobs_and_quota(actor, prepared)
            else:
                blobs = []
            blob = blobs[0] if uploaded else previous.blob
            preview = blobs[-1] if picture else None if remove else previous.preview
            resource.revisions.filter(status='pending').update(status='superseded', reason='作者已提交新修订。')
            revision = Revision.objects.create(resource=resource, title=title, description=description, blob=blob, preview=preview)
            # Preserve submission order when the system clock returns equal or earlier instants.
            if revision.created_at <= previous.created_at:
                Revision.objects.filter(pk=revision.pk).update(created_at=previous.created_at + timedelta(microseconds=1))
            Audit.objects.create(actor=request.user, action='revise', target=f'resource:{resource.id}')
    except BaseException:
        cleanup_prepared(prepared)
        raise
    return success(resource_data(resource, private=True), 201)


def filtered_resources(request, private=False):
    result = Resource.objects.select_related('author', 'published_revision__blob', 'published_revision__preview').all()
    if not private:
        result = result.filter(state='published', published_revision__isnull=False)
    category = request.GET.get('category', '')
    if category:
        if category not in ('characters', 'presets'):
            raise ApiError('资源分类无效。')
        result = result.filter(category=category)
    query = request.GET.get('q', '').strip()[:120]
    if query:
        if private:
            result = result.filter(Q(revisions__title__icontains=query) | Q(revisions__description__icontains=query)).distinct()
        else:
            result = result.filter(Q(published_revision__title__icontains=query) | Q(published_revision__description__icontains=query))
    result = with_counts(result, request.user)
    return result.order_by('-created_at') if private else result.order_by('-published_at', '-id')


@endpoint()
def resource_list(request):
    return success(paginate(filtered_resources(request), request, resource_data))


@endpoint(access='user')
def my_resources(request):
    result = with_counts(Resource.objects.filter(author=request.user).select_related('author'), request.user).order_by('-created_at')
    return success(paginate(result, request, lambda item: resource_data(item, private=True)))


@endpoint()
def detail(request, resource_id):
    resource = with_counts(Resource.objects.select_related('author', 'published_revision__blob', 'published_revision__preview').filter(pk=resource_id), request.user).first()
    private = request.GET.get('private') == '1'
    if not resource:
        raise ApiError('资源不存在或暂未发布。', 'not_found', 404)
    if private:
        if not request.user.is_authenticated or (request.user.id != resource.author_id and request.user.role not in ('admin', 'owner')):
            raise ApiError('投稿不存在。', 'not_found', 404)
        if request.user.banned_at:
            raise ApiError('账号已被封禁。', 'account_banned', 403)
    elif resource.state != 'published' or not resource.published_revision_id:
        raise ApiError('资源不存在或暂未发布。', 'not_found', 404)
    result = resource_data(resource, private=private)
    if private:
        result['revisions'] = [revision_data(r) for r in resource.revisions.select_related('blob', 'preview')[:50]]
    return success(result)


@endpoint(access='admin')
def reviews(request):
    result = []
    for revision in Revision.objects.filter(status='pending').select_related('blob', 'preview', 'resource__author').order_by('created_at')[:200]:
        item = revision_data(revision)
        item.update(category=revision.resource.category,
                    author={'id': revision.resource.author_id, 'name': display_label(revision.resource.author),
                            'email': revision.resource.author.email})
        result.append(item)
    return success({'items': result})


@endpoint(('POST',), access='admin')
def review(request, revision_id):
    body = json_body(request)
    action, reason = body.get('action'), text_value(body, 'reason', 500)
    if action not in ('approve', 'reject'):
        raise ApiError('审核操作无效。')
    if action == 'reject' and not reason:
        raise ApiError('驳回时请填写原因。', fields={'reason': '请填写驳回原因。'})
    with transaction.atomic():
        actor = actor_locked(request, admin=True)
        revision = Revision.objects.select_related('resource').filter(pk=revision_id).first()
        if not revision:
            raise ApiError('投稿不存在。', 'not_found', 404)
        if revision.status != 'pending':
            raise ApiError('这份投稿已处理或已被新修订替换，请刷新。', 'review_conflict', 409)
        revision.status = 'approved' if action == 'approve' else 'rejected'
        revision.reviewer, revision.reason, revision.reviewed_at = actor, reason, timezone.now()
        revision.save(update_fields=['status', 'reviewer', 'reason', 'reviewed_at'])
        resource = revision.resource
        if action == 'approve':
            resource.state, resource.published_revision, resource.published_at = 'published', revision, timezone.now()
            resource.unpublish_reason = ''
            resource.save(update_fields=['state', 'published_revision', 'published_at', 'unpublish_reason'])
        Audit.objects.create(actor=actor, action=action, target=f'revision:{revision.id}', reason=reason)
    return success({'message': '审核已完成。'})


@endpoint(access='admin')
def manage_resources(request):
    return success(paginate(filtered_resources(request, private=True), request, lambda item: resource_data(item, private=True)))


@endpoint(('POST',), access='admin')
def publication(request, resource_id):
    body = json_body(request)
    action, reason = body.get('action'), text_value(body, 'reason', 500)
    if action not in ('unpublish', 'restore'):
        raise ApiError('资源操作无效。')
    if action == 'unpublish' and not reason:
        raise ApiError('下架时请填写原因。', fields={'reason': '请填写下架原因。'})
    with transaction.atomic():
        actor = actor_locked(request, admin=True)
        resource = Resource.objects.filter(pk=resource_id).first()
        if not resource:
            raise ApiError('资源不存在。', 'not_found', 404)
        if action == 'restore' and not resource.published_revision_id:
            raise ApiError('该投稿尚未有审核通过的版本。')
        resource.state = 'unpublished' if action == 'unpublish' else 'published'
        resource.unpublish_reason = reason if action == 'unpublish' else ''
        resource.save(update_fields=['state', 'unpublish_reason'])
        Audit.objects.create(actor=actor, action=action, target=f'resource:{resource.id}', reason=reason)
    return success({'message': '资源已下架。' if action == 'unpublish' else '资源已恢复。'})


def range_bounds(value, size):
    if not value.startswith('bytes=') or ',' in value:
        raise ApiError('下载范围无效。', 'invalid_range', 416)
    try:
        start, end = value[6:].split('-', 1)
        if not start:
            length = int(end)
            if length <= 0:
                raise ValueError()
            start, end = max(0, size - length), size - 1
        else:
            start, end = int(start), int(end) if end else size - 1
        if start < 0 or start >= size or end < start:
            raise ValueError()
        return start, min(end, size - 1)
    except ValueError:
        raise ApiError('下载范围无效。', 'invalid_range', 416)


@endpoint(('GET', 'HEAD'))
def download(request, revision_id, review=False):
    from .download_tickets import checked_revision, download_actor
    actor = download_actor(request, revision_id, review)
    revision, public = checked_revision(actor, revision_id, review)
    resource = revision.resource
    path = (settings.PRIVATE_ROOT / revision.blob.storage_name).resolve()
    if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()) or not path.is_file():
        raise ApiError('文件暂时不可用，请联系管理员。', 'file_missing', 404)
    disposition = content_disposition_header(True, revision.blob.original_name)
    if settings.X_ACCEL_DOWNLOADS:
        response = HttpResponse(content_type='application/octet-stream')
        response['X-Accel-Redirect'] = '/_modshare_private/' + revision.blob.storage_name
    elif request.method == 'HEAD':
        response = HttpResponse(content_type='application/octet-stream')
        response['Content-Length'] = str(revision.blob.size)
    elif request.headers.get('Range'):
        start, end = range_bounds(request.headers['Range'], revision.blob.size)
        def chunks():
            with path.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        response = StreamingHttpResponse(chunks(), status=206, content_type='application/octet-stream')
        response['Content-Range'] = f'bytes {start}-{end}/{revision.blob.size}'
        response['Content-Length'] = str(end - start + 1)
    else:
        response = FileResponse(path.open('rb'), content_type='application/octet-stream')
    response['Content-Disposition'] = disposition
    response['Referrer-Policy'] = 'no-referrer'
    response['Accept-Ranges'] = 'bytes'
    if public and not review and request.method == 'GET' and not request.headers.get('Range'):
        record_download(actor, resource)
    return response
