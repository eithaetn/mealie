from django.urls import path, re_path

from mealie_drf.foods.views import FoodDetailView, FoodListView, FoodMergeView
from mealie_drf.units.views import UnitDetailView, UnitListView, UnitMergeView, route_not_found, slash_redirect
from mealie_drf.views import health

HEALTH_PATH = "/_drf/health/"

urlpatterns = [path(HEALTH_PATH.lstrip("/"), health, name="drf-health")]
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
