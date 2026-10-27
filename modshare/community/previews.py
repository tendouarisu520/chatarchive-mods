"""Validated resource examples, served through revision permissions."""
import hashlib
import io
import os
import uuid
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.utils.cache import get_conditional_response, patch_vary_headers
from django.utils.http import content_disposition_header
from .common import ApiError, endpoint
from .models import Revision, User

MAX_PIXELS = 16_000_000
MAX_EDGE = 8192
MAX_CARD_CACHE_BYTES = 128_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def prepare_preview(upload):
    if upload.size > settings.MAX_PREVIEW_BYTES:
        raise ApiError('例图不能超过 2MB（2,000,000 字节）。', 'preview_too_large', 413, {'preview': '请选择 2MB 以内的图片。'})
    name = upload.name
    if not name or len(name) > 200 or any(c in name for c in '/\\:') or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ApiError('例图文件名不符合要求。', fields={'preview': '请重命名后上传。'})
    allowed = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'webp': 'WEBP'}
    extension = Path(name).suffix.lstrip('.').lower()
    if extension not in allowed or not upload.size:
        raise ApiError('例图仅支持 PNG、JPG 和 WebP 静态图片。', fields={'preview': '请选择有效的静态图片。'})
    upload.seek(0)
    data = upload.read(settings.MAX_PREVIEW_BYTES + 1)
    if len(data) > settings.MAX_PREVIEW_BYTES:
        raise ApiError('例图不能超过 2MB。', 'preview_too_large', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > MAX_PIXELS or max(source.size) > MAX_EDGE:
                    raise ApiError('例图尺寸过大，请缩小后上传。', 'preview_dimensions', fields={'preview': '最长边不超过 8192 像素，总像素不超过 1600 万。'})
                if source.format != allowed[extension] or getattr(source, 'is_animated', False):
                    raise ApiError('例图格式与后缀不匹配，或不是静态图片。', fields={'preview': '请选择 PNG、JPG 或 WebP 静态图片。'})
                source.verify()
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                normalized = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                output = io.BytesIO()
                normalized.save(output, format='WEBP', quality=88, method=4)
                normalized.close()
                image.close()
        data = output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ApiError('例图尺寸过大，请缩小后上传。', 'preview_dimensions')
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise ApiError('例图损坏或不是有效图片。', fields={'preview': '请重新导出为 PNG、JPG 或 WebP。'})
    if len(data) > settings.MAX_PREVIEW_BYTES:
        raise ApiError('例图处理后仍过大，请缩小图片后上传。', 'preview_too_large', 413)
    blob_id = uuid.uuid4()
    storage_name = f'{blob_id.hex}.blob'
    path = settings.PRIVATE_ROOT / storage_name
    try:
        with path.open('xb') as destination:
            destination.write(data)
        os.chmod(path, 0o640)
        return {'id': blob_id, 'storage_name': storage_name, 'original_name': Path(name).stem[:180] + '.webp',
                'extension': 'webp', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def preview_data(revision):
    if not revision.preview_id:
        return None
    url=f'{settings.APP_BASE}/preview/{revision.id}/'
    return {'url': url, 'thumbnail_url':url+'?size=card', 'name': revision.preview.original_name,
            'size': revision.preview.size}


def card_path(source,blob):
    root=settings.TEMP_ROOT/'preview-cards'
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.is_symlink():raise OSError('Unsafe preview cache directory')
    target=root/(blob.sha256+'-640-q78.webp')
    if target.is_symlink():raise OSError('Unsafe preview cache entry')
    if target.is_file():return target
    temporary=root/(uuid.uuid4().hex+'.tmp')
    try:
        with Image.open(source) as image:
            image.thumbnail((640,640),Image.Resampling.LANCZOS)
            image.save(temporary,format='WEBP',quality=78,method=3)
        os.chmod(temporary,0o640)
        os.replace(temporary,target)
        cached=[]
        for candidate in root.glob('*.webp'):
            try:
                stat=candidate.stat();cached.append((stat.st_mtime,candidate,stat.st_size))
            except OSError:continue
        total=sum(entry[2] for entry in cached)
        for _,candidate,length in sorted(cached):
            if total<=MAX_CARD_CACHE_BYTES:break
            if candidate==target:continue
            try:candidate.unlink();total-=length
            except OSError:pass
        return target
    finally:
        temporary.unlink(missing_ok=True)


@endpoint(('GET', 'HEAD'))
def preview(request, revision_id):
    actor = User.objects.filter(pk=request.user.pk).first() if request.user.is_authenticated else None
    if actor and actor.banned_at:
        raise ApiError('账号已被封禁。', 'account_banned', 403)
    revision = Revision.objects.select_related('preview', 'resource').filter(pk=revision_id).first()
    if not revision or not revision.preview_id:
        raise ApiError('例图不存在或暂未发布。', 'not_found', 404)
    resource = revision.resource
    public = resource.state == 'published' and resource.published_revision_id == revision.id
    private = actor and (actor.pk == resource.author_id or actor.role in ('admin', 'owner'))
    if not public and not private:
        raise ApiError('例图不存在或暂未发布。', 'not_found', 404)
    size=request.GET.get('size','full')
    if size not in ('full','card'):
        raise ApiError('例图尺寸参数无效。')
    path = (settings.PRIVATE_ROOT / revision.preview.storage_name).resolve()
    if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()) or not path.is_file():
        raise ApiError('例图暂时不可用。', 'file_missing', 404)
    original=path
    try:
        if size=='card':path=card_path(original,revision.preview)
        length=path.stat().st_size
    except (OSError,ValueError):
        path=original
        length=revision.preview.size
    try:
        response=(HttpResponse(content_type='image/webp') if request.method=='HEAD'
                  else FileResponse(path.open('rb'),content_type='image/webp'))
    except (OSError,ValueError):
        # A concurrent cache prune can remove the card after stat succeeds.
        path=original
        length=revision.preview.size
        response=(HttpResponse(content_type='image/webp') if request.method=='HEAD'
                  else FileResponse(original.open('rb'),content_type='image/webp'))
    variant='card640q78-v1' if path!=original else 'full-v1'
    etag='"'+revision.preview.sha256+'-'+variant+'"'
    cache_policy='private, no-cache' if public else 'private, no-store'
    if public:
        headers={'ETag':etag,'Cache-Control':cache_policy,'Vary':'Cookie'}
        conditional=get_conditional_response(request,etag=etag,response=HttpResponse(headers=headers))
        if conditional.status_code!=200:
            response.close()
            for name,value in headers.items():conditional[name]=value
            return conditional
    response['Content-Length'] = str(length)
    response['Content-Disposition'] = content_disposition_header(False, 'preview.webp')
    response['Cache-Control'] = cache_policy
    response['ETag'] = etag
    patch_vary_headers(response, ('Cookie',))
    response['X-Content-Type-Options'] = 'nosniff'
    return response
