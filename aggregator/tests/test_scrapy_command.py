from django.core.management import call_command


def test_crawl_scrapy_dry_run_command_outputs_sources(db, capsys):
    call_command("crawl_scrapy", "--dry-run")

    output = capsys.readouterr().out

    assert "Dry run" in output
