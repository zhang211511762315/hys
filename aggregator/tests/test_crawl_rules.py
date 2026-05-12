from aggregator.models import Source
from aggregator.services.crawl_rules import is_crawlable_url


def make_source(**kwargs):
    defaults = {
        "name": "NUC",
        "url": "https://www.nuc.edu.cn/",
        "source_type": Source.SourceType.OFFICIAL_SITE,
        "allowed_domains": ["www.nuc.edu.cn"],
        "allowed_path_prefixes": ["/info/", "/xwdt"],
    }
    defaults.update(kwargs)
    return Source(**defaults)


def test_crawl_rules_allow_configured_same_domain_paths():
    assert is_crawlable_url(make_source(), "https://www.nuc.edu.cn/info/1001/1234.htm") is True
    assert is_crawlable_url(make_source(), "https://www.nuc.edu.cn/xwdt.htm") is True


def test_crawl_rules_block_external_attachment_and_login_search_urls():
    source = make_source()

    assert is_crawlable_url(source, "https://example.com/info/1001/1234.htm") is False
    assert is_crawlable_url(source, "https://www.nuc.edu.cn/files/report.pdf") is False
    assert is_crawlable_url(source, "https://www.nuc.edu.cn/virtual_attach_file.vsb?e=.doc") is False
    assert is_crawlable_url(source, "https://www.nuc.edu.cn/system/_content/download.jsp?wbfileid=abc") is False
    assert is_crawlable_url(source, "https://www.nuc.edu.cn/xwdt/%3Cspan%3Ebad%3C/span%3E") is False
    assert is_crawlable_url(source, "https://www.nuc.edu.cn/login") is False
    assert is_crawlable_url(source, "https://www.nuc.edu.cn/search.jsp?keyword=test") is False
