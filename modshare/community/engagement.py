"""Public interaction counts. Calendar periods always use the site's Beijing timezone."""
from datetime import datetime, time, timedelta
from django.db import transaction
from django.db.models import Count, Exists, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from .common import ApiError, endpoint, json_body, success, throttle
from .models import DownloadEvent, Favorite, Resource


def event_count(events):
    # Independent aggregates avoid a downloads × favorites join and long SQLite write locks.
    grouped=events.filter(resource_id=OuterRef('pk')).order_by().values('resource_id').annotate(total=Count('pk')).values('total')
    return Coalesce(Subquery(grouped,output_field=IntegerField()),0)


def rating_summary(positive,negative):
    total=positive+negative
    label,key='暂无评价','unrated'
    if total:
        for threshold,title,value in [(95,'好评如潮','excellent'),(70,'多半好评','positive'),
            (40,'褒贬不一','mixed'),(20,'多半差评','negative'),(0,'差评如潮','poor')]:
            if positive*100>=threshold*total:
                label,key=title,value;break
    return {'label':label,'key':key,'total':total,'positive_percent':positive*1000//total/10 if total else None,
            'small_sample':0<total<10}


def with_counts(queryset, user=None):
    queryset = queryset.annotate(
        download_count=event_count(DownloadEvent.objects.filter(user__banned_at__isnull=True)),
        favorite_count=event_count(Favorite.objects.filter(active=True,user__banned_at__isnull=True)),
        dislike_count=event_count(Favorite.objects.filter(disliked=True,user__banned_at__isnull=True)))
    if user and user.is_authenticated:
        queryset = queryset.annotate(liked=Exists(Favorite.objects.filter(
            resource_id=OuterRef('pk'), user_id=user.pk, active=True, user__banned_at__isnull=True)),
            disliked=Exists(Favorite.objects.filter(resource_id=OuterRef('pk'), user_id=user.pk, disliked=True, user__banned_at__isnull=True)))
    return queryset


def counts(resource):
    if not hasattr(resource, 'download_count'):
        resource = with_counts(Resource.objects.filter(pk=resource.pk)).get()
    return {'download_count':resource.download_count, 'favorite_count':resource.favorite_count,
            'dislike_count':resource.dislike_count, 'liked':bool(getattr(resource, 'liked', False)),
            'disliked':bool(getattr(resource, 'disliked', False)),
            'rating':rating_summary(resource.favorite_count,resource.dislike_count)}


def record_download(actor, resource):
    now = timezone.now()
    DownloadEvent.objects.get_or_create(user=actor, resource=resource, day=timezone.localdate(now),
        defaults={'created_at':now})


@endpoint(('POST',), access='active')
def favorite(request, resource_id):
    return set_reaction(request,resource_id,'liked')


@endpoint(('POST',), access='active')
def dislike(request, resource_id):
    return set_reaction(request,resource_id,'disliked')


def set_reaction(request,resource_id,field):
    from .resources import actor_locked
    body = json_body(request)
    if type(body.get(field)) is not bool:
        raise ApiError('请指定是否喜爱或差评该作品。')
    throttle('reaction-user', str(request.user.pk), 120, 60)
    with transaction.atomic():
        actor = actor_locked(request)
        resource = Resource.objects.filter(pk=resource_id, state='published', published_revision__isnull=False).first()
        if not resource:
            raise ApiError('作品不存在或已下架。', 'not_found', 404)
        if body[field]:
            entry, _ = Favorite.objects.get_or_create(user=actor,resource=resource,
                defaults={'active':False,'created_at':timezone.now()})
            entry.active=field=='liked';entry.disliked=field=='disliked'
            # A first negative vote must not establish the first positive vote's date.
            if entry.active and entry.first_liked_at is None:
                entry.first_liked_at=timezone.now()
            entry.save(update_fields=['active','disliked','first_liked_at'])
        else:
            Favorite.objects.filter(user=actor,resource=resource).update(**{'active' if field=='liked' else 'disliked':False})
        result = with_counts(Resource.objects.filter(pk=resource.pk),actor).get()
    return success(counts(result))


def period_bounds(period):
    today=timezone.localdate(timezone.now())
    if period=='all': return None,None
    start = today if period=='day' else today-timedelta(days=today.weekday()) if period=='week' else today.replace(day=1)
    end = start+timedelta(days=1 if period=='day' else 7) if period!='month' else (start.replace(day=28)+timedelta(days=4)).replace(day=1)
    return tuple(timezone.make_aware(datetime.combine(d,time.min)) for d in (start,end))


@endpoint(('GET',))
def rankings(request):
    from .resources import paginate, resource_data
    metric=request.GET.get('metric','downloads'); period=request.GET.get('period','day')
    category=request.GET.get('category','')
    if metric not in ('downloads','likes') or period not in ('day','week','month','all') or category not in ('','characters','presets'):
        raise ApiError('榜单筛选条件无效。')
    events=DownloadEvent.objects.filter(user__banned_at__isnull=True) if metric=='downloads' else Favorite.objects.filter(active=True,user__banned_at__isnull=True)
    start,end=period_bounds(period)
    if start:
        date_field='created_at' if metric=='downloads' else 'first_liked_at'
        events=events.filter(**{date_field+'__gte':start,date_field+'__lt':end})
    queryset=with_counts(Resource.objects.filter(state='published',published_revision__isnull=False)
        .select_related('author','published_revision__blob','published_revision__preview'),request.user)
    if category: queryset=queryset.filter(category=category)
    queryset=queryset.annotate(score=event_count(events)).filter(score__gt=0).order_by('-score','-published_at','id')
    result=paginate(queryset,request,lambda resource:dict(resource_data(resource),score=resource.score))
    for position,item in enumerate(result['items'],start=(result['page']-1)*24+1): item['rank']=position
    result.update(metric=metric,period=period,category=category,starts_at=start.isoformat() if start else None,
        ends_at=end.isoformat() if end else None,timezone='Asia/Shanghai')
    return success(result)
