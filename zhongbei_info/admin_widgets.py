"""Bound related-object forms independently of production table size."""
from django.contrib import admin


class BoundedRelationsAdmin(admin.ModelAdmin):
    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        # Keep configured autocomplete widgets; remaining relations use paged
        # lookup dialogs instead of materializing every object and its body.
        self.raw_id_fields = tuple(dict.fromkeys([
            *self.raw_id_fields,
            *(field.name for field in model._meta.get_fields()
              if not field.auto_created and (field.many_to_one or field.many_to_many)
              and field.name not in self.autocomplete_fields),
        ]))
