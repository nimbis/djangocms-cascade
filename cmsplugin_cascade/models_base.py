# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.html import mark_safe, format_html_join
from jsonfield.fields import JSONField
from cms.models import CMSPlugin
from cms.plugin_pool import plugin_pool
from cms.utils.placeholder import get_placeholder_conf


@python_2_unicode_compatible
class CascadeModelBase(CMSPlugin):
    """
    The container to hold additional HTML element tags.
    """
    class Meta:
        abstract = True

    cmsplugin_ptr = models.OneToOneField(CMSPlugin, related_name='+', parent_link=True)
    glossary = JSONField(blank=True, default={})

    def __str__(self):
        return self.plugin_class.get_identifier(self)

    @property
    def plugin_class(self):
        if not hasattr(self, '_plugin_class'):
            self._plugin_class = self.get_plugin_class()
        return self._plugin_class

    @property
    def tag_type(self):
        return self.plugin_class.get_tag_type(self)

    @property
    def css_classes(self):
        css_classes = self.plugin_class.get_css_classes(self)
        return mark_safe(' '.join(c for c in css_classes if c))

    @property
    def inline_styles(self):
        inline_styles = self.plugin_class.get_inline_styles(self)
        return format_html_join(' ', '{0}: {1};', (s for s in inline_styles.items() if s[1]))

    @property
    def html_tag_attributes(self):
        attributes = self.plugin_class.get_html_tag_attributes(self)
        return format_html_join(' ', '{0}="{1}"', ((attr, val) for attr, val in attributes.items() if val))

    def get_parent_glossary(self):
        """
        Return the glossary from the parent of this object. If there is no parent, retrieve
        the glossary from the placeholder settings, if configured.
        """
        for model in CascadeModelBase._get_cascade_elements():
            try:
                parent = model.objects.get(id=self.parent_id)
            except model.DoesNotExist:
                continue
            else:
                return parent.get_complete_glossary()
        # use self.placeholder.glossary as the starting dictionary
        template = self.placeholder.page.template if self.placeholder.page else None
        return get_placeholder_conf('glossary', self.placeholder.slot, template=template, default={})

    def get_complete_glossary(self):
        """
        Return the parent glossary for this model object merged with the current object.
        This is done by starting from the root element down to the current element and enriching
        the glossary with each models's own glossary.
        """
        if not hasattr(self, '_complete_glossary_cache'):
            self._complete_glossary_cache = self.get_parent_glossary().copy()
            self._complete_glossary_cache.update(self.glossary or {})
        return self._complete_glossary_cache

    def sanitize_children(self):
        """
        Recursively walk down the plugin tree and invoke method ``save(sanitize_only=True)`` for
        each child.
        """
        for model in CascadeModelBase._get_cascade_elements():
            # execute query to not iterate over SELECT ... FROM while updating other models
            children = list(model.objects.filter(parent_id=self.id))
            for child in children:
                child.save(sanitize_only=True)
                child.sanitize_children()

    def save(self, sanitize_only=False, *args, **kwargs):
        """
        A hook which let the plugin instance sanitize the current object model while saving it.
        With ``sanitize_only=True``, the current model object only is saved when the method
        ``sanitize_model()`` from the corresponding plugin actually changed the glossary.
        """
        sanitized = self.plugin_class.sanitize_model(self)
        if sanitize_only:
            if sanitized:
                super(CascadeModelBase, self).save(no_signals=True)
        else:
            super(CascadeModelBase, self).save(*args, **kwargs)

    @classmethod
    def _get_cascade_elements(cls):
        """
        Returns a set of models which are derived from ``CascadeModelBase``. This set shall be used
        for traversing the plugin tree of interconnected Cascade models. Currently, Cascade itself
        offers only one model, namely ``CascadeElement``, but a third party library may extend
        ``CascadeModelBase`` and add arbitrary model fields.
        """
        if not hasattr(cls, '_cached_cascade_elements'):
            cce = set([p.model._meta.concrete_model for p in plugin_pool.get_all_plugins()
                       if issubclass(p.model, cls)])
            cls._cached_cascade_elements = cce
        return cls._cached_cascade_elements
