import uuid
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AccountManager(UserManager):
    def create_user(self, username=None, email=None, password=None, **extra):
        if not email:
            raise ValueError('Email is required')
        return super().create_user(username or uuid.uuid4().hex, email.strip().casefold(), password, **extra)

    def create_superuser(self, username=None, email=None, password=None, **extra):
        extra.update(role='owner', is_staff=True, is_superuser=True)
        return self.create_user(username, email, password, **extra)


class User(AbstractUser):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=40, default='旅人')
    role = models.CharField(max_length=10, choices=[('user', '用户'), ('admin', '管理员'), ('owner', '超级管理员')], default='user')
    banned_at = models.DateTimeField(null=True, blank=True)
    ban_reason = models.CharField(max_length=500, blank=True)
    objects = AccountManager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['role'], condition=Q(role='owner'), name='one_modshare_owner')]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().casefold()
        super().save(*args, **kwargs)


class EmailChallenge(models.Model):
    email = models.EmailField()
    purpose = models.CharField(max_length=10)
    code_hash = models.CharField(max_length=64)
    sent_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['email', 'purpose'], name='one_email_challenge')]


class Throttle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)


class Audit(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    target = models.CharField(max_length=120)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']


class Blob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    storage_name = models.CharField(max_length=50, unique=True)
    original_name = models.CharField(max_length=200)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    extension = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)


class Resource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='resources')
    category = models.CharField(max_length=12, choices=[('characters', '素材'), ('presets', '预设')])
    state = models.CharField(max_length=12, default='pending', choices=[('pending', '待审核'), ('published', '已发布'), ('unpublished', '已下架')])
    published_revision = models.ForeignKey('Revision', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    published_at = models.DateTimeField(null=True)
    unpublish_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['state', 'category', '-published_at'])]


class Revision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='revisions')
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=20000)
    blob = models.ForeignKey(Blob, on_delete=models.PROTECT, related_name='revisions')
    preview = models.ForeignKey(Blob, on_delete=models.PROTECT, null=True, blank=True, related_name='preview_revisions')
    status = models.CharField(max_length=12, default='pending', choices=[('pending', '待审核'), ('approved', '已通过'), ('rejected', '已驳回'), ('superseded', '已替换')])
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='reviews')
    reason = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class DailyUpload(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    day = models.DateField()
    count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'day'], name='one_daily_quota'),
                       models.CheckConstraint(condition=Q(count__lte=5), name='daily_quota_at_most_five')]


class StorageUsage(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    bytes = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name='one_storage_counter')]


class DownloadEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='downloads')
    day = models.DateField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'resource', 'day'], name='one_download_per_day')]
        indexes = [models.Index(fields=['resource', 'created_at'])]


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='favorites')
    active = models.BooleanField(default=True)
    disliked = models.BooleanField(default=False)
    first_liked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'resource'], name='one_favorite_per_user'),
                       models.CheckConstraint(condition=Q(active=False) | Q(disliked=False), name='one_reaction_direction')]
        indexes = [models.Index(fields=['resource', 'active', 'first_liked_at'])]
