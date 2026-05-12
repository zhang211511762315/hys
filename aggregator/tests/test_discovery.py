from aggregator.services.discovery import discover_article_links, discover_listing_links, discover_school_sources


def test_discover_article_links_keeps_internal_info_pages():
    html = """
    <a href="info/1013/53873.htm">学校新闻</a>
    <a href="https://www.nuc.edu.cn/info/1014/51483.htm">招聘公告</a>
    <a href="https://example.com/info/1.htm">外部链接</a>
    <a href="xxgk.htm#tips">概况</a>
    """

    links = discover_article_links(html, "https://www.nuc.edu.cn/")

    assert links == [
        "https://www.nuc.edu.cn/info/1013/53873.htm",
        "https://www.nuc.edu.cn/info/1014/51483.htm",
    ]


def test_discover_article_links_keeps_detail_news_pages():
    html = """
    <a href="/detail/news?id=399369&menu_id=23295">Career News</a>
    <a href="/module/news?menu_id=23298&type_id=10831">News List</a>
    """

    links = discover_article_links(html, "http://zbjy.nuc.edu.cn/")

    assert links == ["http://zbjy.nuc.edu.cn/detail/news?id=399369&menu_id=23295"]


def test_discover_school_sources_extracts_college_sites():
    html = """
    <a href="http://jdgc.nuc.edu.cn/">机电工程学院</a>
    <a href="http://cst.nuc.edu.cn">计算机科学与技术学院（大数据学院）</a>
    <a href="http://www.moe.gov.cn/">教育部</a>
    <a href="xxjg.htm">学校机构</a>
    """

    sources = discover_school_sources(html, "https://www.nuc.edu.cn/jxjg.htm")

    assert sources == [
        ("机电工程学院", "http://jdgc.nuc.edu.cn/"),
        ("计算机科学与技术学院（大数据学院）", "http://cst.nuc.edu.cn/"),
    ]


def test_discover_listing_links_finds_internal_news_and_notice_pages():
    html = """
    <a href="xwdt.htm">News</a>
    <a href="/tzgg.htm">Notice</a>
    <a href="info/1013/53873.htm">Article</a>
    <a href="https://example.com/tzgg.htm">External</a>
    <a href="javascript:void(0)">JavaScript</a>
    """

    links = discover_listing_links(html, "https://www.nuc.edu.cn/")

    assert links == [
        "https://www.nuc.edu.cn/xwdt.htm",
        "https://www.nuc.edu.cn/tzgg.htm",
    ]
