from django.db import models
from django.urls import reverse
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "分类"
        verbose_name_plural = "分类"

    def __str__(self):
        return self.name

class Tag(TimeStampedModel):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "标签"
        verbose_name_plural = "标签"

    def __str__(self):
        return self.name


class Source(TimeStampedModel):
    class SourceType(models.TextChoices):
        OFFICIAL_SITE = "official_site", "中北官网"
        COLLEGE_SITE = "college_site", "学院官网"
        DEPARTMENT_SITE = "department_site", "部门网站"
        SOCIAL_LINK = "social_link", "社媒链接"
        WECHAT_LINK = "wechat_link", "公众号链接"
        MANUAL_URL = "manual_url", "手动链接"

    class Priority(models.IntegerChoices):
        HIGH = 10, "重点源"
        NORMAL = 50, "普通源"
        LOW = 100, "低频源"

    class SourceGroup(models.TextChoices):
        PORTAL = "portal", "主站/门户"
        COLLEGE = "college", "学院"
        ADMIN = "admin", "行政部门"
        STUDENT_SERVICE = "student_service", "学生服务"
        STUDENT_ORG = "student_org", "学生组织"
        WECHAT = "wechat", "微信公众号"

    class ScheduleGroup(models.TextChoices):
        WEB_TWICE_DAILY = "web_twice_daily", "官网每日两次"
        SOCIAL_DAILY = "social_daily", "社媒每日一次"
        MANUAL = "manual", "仅手动"

    name = models.CharField(max_length=160)
    url = models.URLField(max_length=500, unique=True)
    source_type = models.CharField(max_length=40, choices=SourceType.choices)
    source_group = models.CharField(max_length=30, choices=SourceGroup.choices, blank=True)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.NORMAL)
    crawl_interval_minutes = models.PositiveIntegerField(default=360)
    crawl_depth = models.PositiveIntegerField(default=2)
    max_articles_per_run = models.PositiveIntegerField(default=50)
    max_list_pages_per_run = models.PositiveIntegerField(default=8)
    enabled = models.BooleanField(default=True)
    crawl_enabled = models.BooleanField(default=True)
    schedule_group = models.CharField(max_length=40, choices=ScheduleGroup.choices, blank=True)
    allowed_domains = models.JSONField(default=list, blank=True)
    allowed_path_prefixes = models.JSONField(default=list, blank=True)
    denied_path_patterns = models.JSONField(default=list, blank=True)
    max_depth = models.PositiveIntegerField(default=6)
    max_pages_per_run = models.PositiveIntegerField(default=5000)
    notes = models.TextField(blank=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    bootstrap_completed_at = models.DateTimeField(null=True, blank=True)
    next_crawl_at = models.DateTimeField(default=timezone.now)
    failure_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["priority", "name"]
        verbose_name = "信息源"
        verbose_name_plural = "信息源"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.schedule_group:
            if self.source_type == self.SourceType.MANUAL_URL:
                self.schedule_group = self.ScheduleGroup.MANUAL
            elif self.source_type in {self.SourceType.SOCIAL_LINK, self.SourceType.WECHAT_LINK}:
                self.schedule_group = self.ScheduleGroup.SOCIAL_DAILY
            else:
                self.schedule_group = self.ScheduleGroup.WEB_TWICE_DAILY
        if not self.source_group:
            if self.source_type == self.SourceType.OFFICIAL_SITE:
                self.source_group = self.SourceGroup.PORTAL
            elif self.source_type == self.SourceType.COLLEGE_SITE:
                self.source_group = self.SourceGroup.COLLEGE
            elif self.source_type == self.SourceType.WECHAT_LINK:
                self.source_group = self.SourceGroup.WECHAT
            elif self.source_type == self.SourceType.SOCIAL_LINK:
                self.source_group = self.SourceGroup.STUDENT_ORG
        if self._state.adding and self.crawl_interval_minutes == 360:
            if self.source_type in {self.SourceType.SOCIAL_LINK, self.SourceType.WECHAT_LINK, self.SourceType.MANUAL_URL}:
                self.crawl_interval_minutes = 1440
            elif self.source_type == self.SourceType.OFFICIAL_SITE:
                self.crawl_interval_minutes = 5
            elif self.source_type == self.SourceType.DEPARTMENT_SITE:
                self.crawl_interval_minutes = 30
            elif self.source_type == self.SourceType.COLLEGE_SITE:
                self.crawl_interval_minutes = 30
        super().save(*args, **kwargs)


class CrawlJob(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="crawl_jobs")
    target_url = models.URLField(max_length=500)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    warning_message = models.TextField(blank=True)
    listing_pages_count = models.PositiveIntegerField(default=0)
    discovered_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    duplicate_skip_count = models.PositiveIntegerField(default=0)
    failed_url_count = models.PositiveIntegerField(default=0)
    direct_fetch_count = models.PositiveIntegerField(default=0)
    relay_fetch_count = models.PositiveIntegerField(default=0)
    near_duplicate_skip_count = models.PositiveIntegerField(default=0)
    ai_call_count = models.PositiveIntegerField(default=0)
    ai_skip_count = models.PositiveIntegerField(default=0)
    ai_fallback_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "抓取任务"
        verbose_name_plural = "抓取任务"

    def __str__(self):
        return f"{self.source} - {self.status}"


class CrawlNetworkEvent(TimeStampedModel):
    schedule_group = models.CharField(max_length=40, blank=True)
    checked_count = models.PositiveIntegerField(default=0)
    reachable_count = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=200)
    probe_urls = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "抓取网络事件"
        verbose_name_plural = "抓取网络事件"

    def __str__(self):
        group = self.schedule_group or "due"
        return f"{group}: {self.reason}"


class CrawlFailure(TimeStampedModel):
    class FailureClass(models.TextChoices):
        TRANSIENT = "transient", "临时失败"
        NETWORK = "network", "网络失败"
        PERMANENT = "permanent", "永久失败"

    crawl_job = models.ForeignKey(CrawlJob, on_delete=models.CASCADE, related_name="failures")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="crawl_failures")
    url = models.URLField(max_length=500)
    error_type = models.CharField(max_length=120, blank=True)
    error_message = models.TextField(blank=True)
    failure_class = models.CharField(max_length=30, choices=FailureClass.choices, default=FailureClass.TRANSIENT)
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    permanent = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "抓取失败URL"
        verbose_name_plural = "抓取失败URL"

    def __str__(self):
        return f"{self.source} - {self.url}"


class RawDocument(TimeStampedModel):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="raw_documents")
    crawl_job = models.ForeignKey(CrawlJob, on_delete=models.SET_NULL, null=True, blank=True)
    url = models.URLField(max_length=500)
    final_url = models.URLField(max_length=500, blank=True)
    title = models.CharField(max_length=300, blank=True)
    html = models.TextField(blank=True)
    extracted_text = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fetched_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "content_hash"], name="unique_source_raw_hash")
        ]
        verbose_name = "原始文档"
        verbose_name_plural = "原始文档"

    def __str__(self):
        return self.title or self.url


class DuplicateGroup(TimeStampedModel):
    fingerprint = models.CharField(max_length=64, unique=True)
    canonical_item = models.ForeignKey(
        "ContentItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="canonical_for_groups",
    )

    class Meta:
        verbose_name = "重复组"
        verbose_name_plural = "重复组"

    def __str__(self):
        return self.fingerprint


class ContentItem(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        FETCHED = "fetched", "已抓取"
        CLEANED = "cleaned", "已清洗"
        OCR_DONE = "ocr_done", "OCR完成"
        CLASSIFIED = "classified", "已分类"
        PUBLISHED = "published", "已发布"
        FAILED = "failed", "失败"
        BLOCKED = "blocked", "已屏蔽"

    class ReviewStatus(models.TextChoices):
        CANDIDATE = "candidate", "候选"
        NEEDS_REVIEW = "needs_review", "待审核"
        PUBLISHED = "published", "已发布"
        BLOCKED = "blocked", "已屏蔽"
        OUT_OF_RANGE = "out_of_range", "超出时间范围"

    class DateConfidence(models.TextChoices):
        EXACT = "exact", "精确日期"
        YEAR_ONLY = "year_only", "仅年份"
        UNKNOWN = "unknown", "未知"

    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="content_items")
    raw_document = models.ForeignKey(RawDocument, on_delete=models.SET_NULL, null=True, blank=True)
    duplicate_group = models.ForeignKey(DuplicateGroup, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    title = models.CharField(max_length=300)
    title_fingerprint = models.CharField(max_length=160, blank=True, db_index=True)
    canonical_url = models.URLField(max_length=500, unique=True)
    summary = models.TextField(blank=True)
    content_text = models.TextField()
    content_hash = models.CharField(max_length=64, db_index=True, blank=True)
    importance_score = models.PositiveIntegerField(default=0, db_index=True)
    review_status = models.CharField(max_length=30, choices=ReviewStatus.choices, default=ReviewStatus.PUBLISHED)
    date_confidence = models.CharField(max_length=30, choices=DateConfidence.choices, default=DateConfidence.UNKNOWN)
    extraction_quality_score = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=True, db_index=True)
    review_reason = models.TextField(blank=True)
    ai_provider = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    published_at = models.DateTimeField(null=True, blank=True)
    source_published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = "内容"
        verbose_name_plural = "内容"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("aggregator:item_detail", kwargs={"pk": self.pk})


class ContentSource(TimeStampedModel):
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name="content_sources")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="discovered_content_sources")
    raw_document = models.ForeignKey(RawDocument, on_delete=models.SET_NULL, null=True, blank=True)
    url = models.URLField(max_length=500)
    source_title = models.CharField(max_length=300, blank=True)
    source_published_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source__name", "url"]
        constraints = [
            models.UniqueConstraint(fields=["content_item", "source", "url"], name="unique_content_source_url")
        ]
        verbose_name = "内容来源"
        verbose_name_plural = "内容来源"

    def __str__(self):
        return f"{self.source} - {self.url}"


class Attachment(TimeStampedModel):
    class AttachmentType(models.TextChoices):
        IMAGE = "image", "图片"
        VIDEO = "video", "视频"
        OTHER = "other", "其他"

    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name="attachments")
    source_url = models.URLField(max_length=500)
    attachment_type = models.CharField(max_length=20, choices=AttachmentType.choices, default=AttachmentType.IMAGE)
    ocr_text = models.TextField(blank=True)
    processed = models.BooleanField(default=False)

    class Meta:
        verbose_name = "附件"
        verbose_name_plural = "附件"

    def __str__(self):
        return self.source_url


class AIJob(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name="ai_jobs")
    provider = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    prompt = models.TextField(blank=True)
    response_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI任务"
        verbose_name_plural = "AI任务"

    def __str__(self):
        return f"{self.provider} - {self.status}"


class AIUsageDaily(TimeStampedModel):
    usage_date = models.DateField()
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=80)
    request_count = models.PositiveIntegerField(default=0)
    prompt_cache_hit_tokens = models.PositiveIntegerField(default=0)
    prompt_cache_miss_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    estimated_prompt_tokens = models.PositiveIntegerField(default=0)
    estimated_completion_tokens = models.PositiveIntegerField(default=0)
    cost_cny = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        ordering = ["-usage_date", "provider", "model"]
        constraints = [
            models.UniqueConstraint(fields=["usage_date", "provider", "model"], name="unique_ai_usage_daily")
        ]
        verbose_name = "AI每日用量"
        verbose_name_plural = "AI每日用量"

    def __str__(self):
        return f"{self.usage_date} {self.provider}/{self.model}"
