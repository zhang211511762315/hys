"""Synthetic regressions for search controls and large-document admin lists."""
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from aggregator.models import RawDocument, Source

pytestmark = pytest.mark.django_db


def test_search_sort_and_date_form_preserve_the_search(client):
    response = client.get('/search/', {'q': '就业 & 招聘', 'category': 'jobs', 'page': 2})
    soup = BeautifulSoup(response.content, 'html.parser')
    for link in soup.select('.sort-group a'):
        params = parse_qs(urlsplit(link['href']).query)
        assert params['q'] == ['就业 & 招聘']
        assert params['category'] == ['jobs']
        assert 'page' not in params
    fields = {i['name']: i.get('value', '') for i in soup.select('.date-group input[name]')}
    assert fields['q'] == '就业 & 招聘'
    assert fields['category'] == 'jobs'
    assert 'page' not in fields


def test_document_list_does_not_fetch_bodies_but_change_form_still_can(client, settings):
    call_command('prepare_public_workspace', verbosity=0)
    settings.PUBLIC_WORKSPACE_ENABLED = True
    source = Source.objects.create(name='synthetic', url='https://example.invalid/', source_type='manual_url')
    marker = 'SYNTHETIC_LARGE_DOCUMENT_BODY'
    doc = RawDocument.objects.create(source=source, url='https://example.invalid/a',
                                     title='Synthetic document', content_hash='synthetic-hash',
                                     html=marker * 1000, extracted_text=marker * 1000)
    RawDocument.objects.bulk_create([
        RawDocument(source=source, url=f'https://example.invalid/{i}', title=f'Synthetic {i}',
                    content_hash=f'synthetic-{i}', html=marker * 100, extracted_text=marker * 100)
        for i in range(51)
    ])
    with CaptureQueriesContext(connection) as queries:
        response = client.get('/admin/aggregator/rawdocument/')
    assert response.status_code == 200
    assert marker.encode() not in response.content
    selections = [q['sql'] for q in queries if 'FROM "aggregator_rawdocument"' in q['sql'] and 'COUNT(' not in q['sql']]
    assert selections
    assert all('"html"' not in sql and '"extracted_text"' not in sql for sql in selections)
    assert any('LIMIT 50' in sql or 'LIMIT 1' in sql for sql in selections)
    detail = client.get(f'/admin/aggregator/rawdocument/{doc.pk}/change/')
    assert detail.status_code == 200
    assert marker.encode() in detail.content


def test_long_duplicate_titles_fit_the_database_and_share_a_group():
    from aggregator.models import ContentItem, DuplicateGroup
    from aggregator.services.dedupe import title_fingerprint
    from aggregator.services.pipeline import _link_duplicate_group

    source = Source.objects.create(name='synthetic', url='https://example.invalid/', source_type='manual_url')
    title = '合成很长的通知标题' * 12
    items = [ContentItem.objects.create(source=source, title=title, title_fingerprint=title_fingerprint(title),
                                       canonical_url=f'https://example.invalid/duplicate-{i}') for i in range(2)]
    for item in items:
        _link_duplicate_group(item)
        item.refresh_from_db()
    assert items[0].duplicate_group_id == items[1].duplicate_group_id
    group = items[0].duplicate_group
    DuplicateGroup._meta.get_field('fingerprint').run_validators(group.fingerprint)
    short = ContentItem.objects.create(source=source, title='合成短标题', canonical_url='https://example.invalid/short')
    _link_duplicate_group(short)
    assert short.duplicate_group.fingerprint == 'title:' + title_fingerprint(short.title)
