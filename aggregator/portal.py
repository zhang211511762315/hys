"""Single feature registry for navigation and acceptance checks."""
import json
from pathlib import Path
from django.conf import settings
from django.contrib import admin
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse


def item(label, href, dependency='hys'):
    return {'label':label, 'href':href, 'dependency':dependency}


def registry():
    hys = [
        {'label':'信息浏览与搜索','features':[item('校园信息首页','/'),item('分类与来源浏览','/sources/portal/'),item('搜索与筛选','/search/')]},
        {'label':'研究与问答','features':[item('研究任务：创建、结果、取消与重放','/research/'),item('问答与会话历史','/ask/')]},
        {'label':'记忆与会话','features':[item('查看、保存、删除与导出记忆','/account/privacy/')]},
        {'label':'来源管理','features':[item('信息源配置与手动抓取','/admin/aggregator/source/'),item('公众号订阅与文章','/hys/rss/dash/','rss'),item('公众号账号绑定与状态','/hys/rss/dash/accounts','rss')]},
        {'label':'内容管理','features':[]},
        {'label':'任务与运行记录','features':[item('Agent 运行与费用概览','/agent/')]},
    ]
    used={f['href'] for g in hys for f in g['features']}
    for model in admin.site._registry:
        app=model._meta.app_label
        if app not in {'aggregator','agent_runtime'}:continue
        href=reverse('admin:%s_%s_changelist'%(app,model._meta.model_name))
        if href in used:continue
        group=hys[4] if app=='aggregator' and model._meta.model_name in {'contentitem','category','tag','rawdocument','duplicategroup','contentsource','attachment'} else hys[5]
        group['features'].append(item(str(model._meta.verbose_name_plural),href))
    return [
        {'slug':'hys','name':'HYS 校园信息','summary':'校园信息、研究问答及来源内容管理','href':'/','dependency':'hys','groups':hys},
        {'slug':'rp-chat','name':'RP Chat','summary':'人物卡、长剧情、记忆与摘要','href':'/rp/','dependency':'rp-chat','groups':[
            {'label':'人物卡','features':[item('人物列表、编辑与复制','/rp/#/chars','rp-chat'),item('导入人物卡与文档','/rp/#/upload','rp-chat')]},
            {'label':'剧情与聊天','features':[item('全部剧情与历史、生成与重生成','/rp/#/chats','rp-chat')]},
            {'label':'记忆与摘要','features':[item('选择剧情管理记忆与压缩摘要','/rp/#/memories','rp-chat')]},
            {'label':'导入导出','features':[item('导入人物资料','/rp/#/upload','rp-chat'),item('导出全部资料','/rp/#/settings/exports','rp-chat'),item('选择剧情导出','/rp/#/chats','rp-chat')]},
            {'label':'模型与显示设置','features':[item('模型、上下文、显示与主题','/rp/#/settings','rp-chat')]},
        ]},
        {'slug':'mobile-rp','name':'Mobile RP','summary':'SillyTavern 角色聊天与扩展工作台','href':'/mobile-rp/','dependency':'mobile-rp','groups':[
            {'label':'角色与聊天','features':[item('角色与群组、聊天历史','/mobile-rp/?feature=characters','mobile-rp'),item('用户角色','/mobile-rp/?feature=personas','mobile-rp')]},
            {'label':'世界书','features':[item('世界书与触发配置','/mobile-rp/?feature=world-info','mobile-rp')]},
            {'label':'预设与模型连接','features':[item('生成预设与参数','/mobile-rp/?feature=presets','mobile-rp'),item('模型连接','/mobile-rp/?feature=connections','mobile-rp'),item('提示词与格式','/mobile-rp/?feature=formatting','mobile-rp')]},
            {'label':'扩展','features':[item('扩展管理与配置','/mobile-rp/?feature=extensions','mobile-rp')]},
            {'label':'导入导出','features':[item('角色导入导出','/mobile-rp/?feature=characters','mobile-rp'),item('聊天历史与导入导出','/mobile-rp/?feature=chats','mobile-rp')]},
            {'label':'显示与设置','features':[item('界面与用户设置','/mobile-rp/?feature=settings','mobile-rp'),item('背景与显示','/mobile-rp/?feature=backgrounds','mobile-rp')]},
        ]},
    ]


def projects():
    ready={'hys':True,'rp-chat':False,'mobile-rp':False,'rss':False}
    path=getattr(settings,'PORTAL_STATE_FILE','')
    if path:
        try:ready.update({k:v is True for k,v in json.loads(Path(path).read_text()).items() if k in ready})
        except (OSError,ValueError,AttributeError):pass
    data=registry()
    for project in data:
        project['ready']=ready[project['dependency']]
        for group in project['groups']:
            for feature in group['features']:feature['ready']=ready[feature['dependency']]
    return data


def context(request):
    return {'portal_projects':projects()}


def index(request):
    return render(request,'aggregator/projects.html')


def detail(request,slug):
    project=next((p for p in projects() if p['slug']==slug),None)
    if project is None:raise Http404
    return render(request,'aggregator/project.html',{'project':project})
