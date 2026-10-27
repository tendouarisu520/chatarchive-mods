import codecs
import hashlib
import os
import struct
import uuid
import zipfile
from pathlib import Path
from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from .common import ApiError

ARCHIVES = {'zip', '7z', 'rar', 'capk'}
TEXT_FORMATS = {'txt', 'json', 'jsonl', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'xml', 'md', 'csv'}


class BoundedUploadHandler(FileUploadHandler):
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        limit = settings.MAX_PREVIEW_BYTES if self.field_name == 'preview' else settings.MAX_FILE_BYTES
        if self.received > limit:
            if self.field_name == 'preview':
                self.request.mod_preview_excess = True
            else:
                self.request.mod_file_excess = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None


def check_text(upload):
    upload.seek(0)
    prefix = upload.read(4)
    encodings = ['utf-16'] if prefix.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    if prefix.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        encodings = ['utf-32']
    for encoding in encodings:
        upload.seek(0)
        decoder = codecs.getincrementaldecoder(encoding)(errors='strict')
        try:
            while True:
                chunk = upload.read(65536)
                text = decoder.decode(chunk, final=not chunk)
                if any(ord(c) < 32 and c not in '\t\n\r' for c in text):
                    raise ApiError('预设文件须为文本，不能包含二进制内容。')
                if not chunk:
                    upload.seek(0)
                    return
        except UnicodeDecodeError:
            continue
    raise ApiError('文本编码不受支持，请保存为 UTF-8 后上传。')


def is_capk(upload):
    """Validate KPAC v1 framing without extracting or interpreting entries."""
    def read_exact(length):
        if length < 0 or length > upload.size - upload.tell():
            raise ValueError('Invalid CAPK length')
        value = upload.read(length)
        if len(value) != length:
            raise ValueError('Truncated CAPK')
        return value

    def read_string(limit):
        length = 0
        for shift in range(0, 35, 7):
            byte = read_exact(1)[0]
            length |= (byte & 127) << shift
            if not byte & 128:
                if length > limit:
                    raise ValueError('CAPK name too long')
                return read_exact(length).decode('utf-8')
        raise ValueError('Invalid CAPK string length')

    upload.seek(0)
    try:
        if read_exact(8) != b'KPAC\x01\x00\x00\x00' or not read_string(4096).strip():
            return False
        count = struct.unpack('<i', read_exact(4))[0]
        if not 1 <= count <= 4096:
            return False
        for _ in range(count):
            name = read_string(260)
            if not name or len(name) > 260:
                return False
            length = struct.unpack('<i', read_exact(4))[0]
            if length <= 0 or length > upload.size - upload.tell():
                return False
            upload.seek(length, 1)
        return upload.tell() == upload.size
    except (ValueError, OSError):
        return False
    finally:
        upload.seek(0)


def prepare_file(upload, category):
    if category not in ('characters', 'presets'):
        raise ApiError('请选择素材区或预设区。')
    name = upload.name
    if not name or len(name) > 200 or any(c in name for c in '/\\:') or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ApiError('文件名不符合要求，请重命名后上传。')
    extension = Path(name).suffix.lstrip('.').lower()
    allowed = ARCHIVES if category == 'characters' else TEXT_FORMATS
    if extension not in allowed:
        raise ApiError('素材区只接收 ZIP、7Z、RAR、CAPK；预设区只接收支持的文本格式。')
    if upload.size > settings.MAX_FILE_BYTES:
        raise ApiError('文件超过 50MB 上限。', 'file_too_large', 413)
    if upload.size == 0:
        raise ApiError('不能上传空文件。')
    upload.seek(0)
    signature = upload.read(16)
    upload.seek(0)
    if category == 'characters':
        valid = (extension == 'zip' and zipfile.is_zipfile(upload)) or \
                (extension == '7z' and signature.startswith(b'7z\xbc\xaf\x27\x1c') and upload.size >= 32) or \
                (extension == 'rar' and signature.startswith((b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01\x00')) and upload.size >= 16) or \
                (extension == 'capk' and is_capk(upload))
        if not valid:
            raise ApiError('压缩包格式与后缀不匹配，或文件已损坏。')
    else:
        check_text(upload)
    upload.seek(0)
    blob_id = uuid.uuid4()
    storage_name = f'{blob_id.hex}.blob'
    target = settings.PRIVATE_ROOT / storage_name
    digest, size = hashlib.sha256(), 0
    try:
        with target.open('xb') as destination:
            for chunk in upload.chunks(65536):
                size += len(chunk)
                if size > settings.MAX_FILE_BYTES:
                    raise ApiError('文件超过 50MB 上限。', 'file_too_large', 413)
                destination.write(chunk)
                digest.update(chunk)
        os.chmod(target, 0o640)
        return {'id': blob_id, 'storage_name': storage_name, 'original_name': name,
                'size': size, 'sha256': digest.hexdigest(), 'extension': extension}
    except BaseException:
        target.unlink(missing_ok=True)
        raise
