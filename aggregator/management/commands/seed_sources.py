import httpx
from django.core.management.base import BaseCommand

from aggregator.models import Category, Source
from aggregator.services.discovery import discover_school_sources
from aggregator.services.scheduling import recommended_crawl_interval_minutes


class Command(BaseCommand):
    help = "Seed initial Zhongbei University categories and source URLs."

    def handle(self, *args, **options):
        categories = [
            ("通知", "notice"),
            ("招生", "admission"),
            ("科研", "research"),
            ("就业", "career"),
            ("社团", "club"),
            ("学院", "college"),
        ]
        for name, slug in categories:
            Category.objects.get_or_create(name=name, defaults={"slug": slug})

        sources = self._base_sources()
        sources.extend(self._discover_college_sources())
        for name, url, source_type, priority, interval in sources:
            Source.objects.update_or_create(
                url=url,
                defaults={
                    "name": name,
                    "source_type": source_type,
                    "priority": priority,
                    "crawl_interval_minutes": interval or recommended_crawl_interval_minutes(source_type, priority),
                    "crawl_depth": 2,
                    "max_articles_per_run": 50 if priority != Source.Priority.LOW else 25,
                    "max_list_pages_per_run": 10 if priority == Source.Priority.HIGH else 6,
                    "enabled": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(sources)} Zhongbei categories and sources."))

    def _base_sources(self):
        return [
            ("中北大学官网", "https://www.nuc.edu.cn/", Source.SourceType.OFFICIAL_SITE, Source.Priority.HIGH, None),
            ("中北大学教学机构", "https://www.nuc.edu.cn/jxjg.htm", Source.SourceType.OFFICIAL_SITE, Source.Priority.HIGH, None),
            ("中北大学教务部", "http://jwc.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.HIGH, None),
            ("中北大学研究生院", "http://grs.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.HIGH, None),
            ("中北大学本科招生网", "http://zbzs.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.HIGH, None),
            ("中北大学就业信息网", "http://zbjy.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.HIGH, None),
            ("中北大学科学技术研究院", "https://std.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.NORMAL, None),
            ("中北大学国际教育学院", "http://international.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.NORMAL, None),
            ("中北大学继续教育学院", "http://jxjy.nuc.edu.cn/", Source.SourceType.COLLEGE_SITE, Source.Priority.NORMAL, None),
            ("中北大学学科建设办公室", "http://xwb.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.NORMAL, None),
            ("中北大学校友会", "http://xyb.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.LOW, None),
            ("中北大学教育发展基金会", "http://fund.nuc.edu.cn/", Source.SourceType.DEPARTMENT_SITE, Source.Priority.LOW, None),
        ]

    def _discover_college_sources(self):
        url = "https://www.nuc.edu.cn/jxjg.htm"
        try:
            response = httpx.get(url, timeout=30, follow_redirects=True)
            response.raise_for_status()
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Could not discover college sources: {exc}"))
            return []
        return [
            (name, site_url, Source.SourceType.COLLEGE_SITE, Source.Priority.NORMAL, None)
            for name, site_url in discover_school_sources(response.text, url)
        ]
