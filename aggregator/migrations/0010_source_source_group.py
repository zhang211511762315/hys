from django.db import migrations, models


SOURCE_GROUP_CHOICES = [
    ("portal", "主站/门户"),
    ("college", "学院"),
    ("admin", "行政部门"),
    ("student_service", "学生服务"),
    ("student_org", "学生组织"),
    ("wechat", "微信公众号"),
]


def add_source_group_column_if_missing(apps, schema_editor):
    Source = apps.get_model("aggregator", "Source")
    table_name = Source._meta.db_table
    existing_columns = {
        column.name for column in schema_editor.connection.introspection.get_table_description(schema_editor.connection.cursor(), table_name)
    }
    if "source_group" in existing_columns:
        return

    field = models.CharField(blank=True, choices=SOURCE_GROUP_CHOICES, default="", max_length=30)
    field.set_attributes_from_name("source_group")
    schema_editor.add_field(Source, field)


class Migration(migrations.Migration):

    dependencies = [
        ("aggregator", "0009_failure_retry_near_duplicates_cleanup"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_source_group_column_if_missing, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="source",
                    name="source_group",
                    field=models.CharField(blank=True, choices=SOURCE_GROUP_CHOICES, max_length=30),
                ),
            ],
        ),
    ]
