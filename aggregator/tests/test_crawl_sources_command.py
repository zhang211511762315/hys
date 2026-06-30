from django.core.management import call_command

from aggregator.models import Source


def make_source(name: str, url: str) -> Source:
    return Source.objects.create(
        name=name,
        url=url,
        source_type=Source.SourceType.OFFICIAL_SITE,
        priority=Source.Priority.NORMAL,
    )


def test_crawl_sources_continues_after_source_failure(db, monkeypatch, capsys):
    first = make_source("First", "https://www.nuc.edu.cn/")
    second = make_source("Second", "https://grs.nuc.edu.cn/")
    crawled = []

    def fake_ingest_source(source):
        crawled.append(source.id)
        if source.id == first.id:
            raise RuntimeError("network unavailable")
        return 2

    monkeypatch.setattr("aggregator.management.commands.crawl_sources.ingest_source", fake_ingest_source)

    call_command("crawl_sources", "--all", "--limit", "2")

    captured = capsys.readouterr()
    first.refresh_from_db()
    second.refresh_from_db()

    assert crawled == [first.id, second.id]
    assert first.failure_count == 1
    assert second.failure_count == 0
    assert "failed 1 source" in captured.out
