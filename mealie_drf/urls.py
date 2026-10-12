from django.urls import path, re_path

from mealie_drf.foods.views import FoodDetailView, FoodListView, FoodMergeView
from mealie_drf.tags.views import (
    TagDetailView,
    TagEmptyView,
    TagListView,
    TagMergeView,
    TagSlugView,
    tag_route_not_found,
    tag_slash_redirect,
)
from mealie_drf.units.views import UnitDetailView, UnitListView, UnitMergeView, route_not_found, slash_redirect
from mealie_drf.views import health

HEALTH_PATH = "/_drf/health/"

urlpatterns = [path(HEALTH_PATH.lstrip("/"), health, name="drf-health")]
urlpatterns += [
    path("api/organizers/tags", TagListView.as_view(), name="tags-list"),
    path("api/organizers/tags/empty", TagEmptyView.as_view(), {"item_id": "empty"}, name="tags-empty"),
    path("api/organizers/tags/merge", TagMergeView.as_view(), {"item_id": "merge"}, name="tags-merge"),
    path("api/organizers/tags/slug/<str:tag_slug>", TagSlugView.as_view(), name="tags-slug"),
    path("api/organizers/tags/<str:item_id>", TagDetailView.as_view(), name="tags-detail"),
    re_path(r"^api/organizers/tags/(?:(?:slug/[^/]+|[^/]+)/+|/*)$", tag_slash_redirect),
    re_path(r"^api/organizers/tags/.*$", tag_route_not_found),
]

urlpatterns += [
    path("api/units", UnitListView.as_view(), name="units-list"),
    path("api/units/merge", UnitMergeView.as_view(), {"item_id": "merge"}, name="units-merge"),
    path("api/units/<str:item_id>", UnitDetailView.as_view(), name="units-detail"),
    path("api/units/", slash_redirect),
    path("api/units/<str:item_id>/", slash_redirect),
    re_path(r"^api/units/.*$", route_not_found),
]

urlpatterns += [
    path("api/foods", FoodListView.as_view(), name="foods-list"),
    path("api/foods/merge", FoodMergeView.as_view(), {"item_id": "merge"}, name="foods-merge"),
    path("api/foods/<str:item_id>", FoodDetailView.as_view(), name="foods-detail"),
    path("api/foods/", slash_redirect),
    path("api/foods/<str:item_id>/", slash_redirect),
    re_path(r"^api/foods/.*$", route_not_found),
]
