from django.urls import path

from mealie.drf.admin_views import AdminAboutView, AdminConfigView, AdminStatisticsView
from mealie.drf.auth_views import (
    LoginView,
    LogoutView,
    OAuthCallbackView,
    OAuthLoginView,
    OAuthNativeConfigView,
    OAuthNativeTokenView,
    RefreshView,
)
from mealie.drf.image_views import ProfileImageView
from mealie.drf.rating_views import FavoritesView, FavoriteView, RatingsView, RatingView
from mealie.drf.registration_views import ForgotPasswordView, RegistrationView, ResetPasswordView
from mealie.drf.user_views import (
    ApiTokenCreateView,
    ApiTokenDeleteView,
    UserFavoritesView,
    UserPasswordView,
    UserRatingsView,
    UserRatingView,
    UserSelfView,
    UserUpdateView,
)
from mealie.drf.views import AppInfoView, AppStartupInfoView, AppThemeView

handler500 = "mealie.drf.errors.server_error"

urlpatterns = [
    path("api/users/<uuid:id>/image", ProfileImageView.as_view()),
    path("api/users/<uuid:id>/ratings", RatingsView.as_view()),
    path("api/users/<uuid:id>/favorites", FavoritesView.as_view()),
    path("api/users/<uuid:id>/ratings/<str:slug>", RatingView.as_view()),
    path("api/users/<uuid:id>/favorites/<str:slug>", FavoriteView.as_view()),
    path("api/users/register", RegistrationView.as_view()),
    path("api/users/forgot-password", ForgotPasswordView.as_view()),
    path("api/users/reset-password", ResetPasswordView.as_view()),
    path("api/auth/oauth", OAuthLoginView.as_view()),
    path("api/auth/oauth/callback", OAuthCallbackView.as_view()),
    path("api/auth/oauth/native/config", OAuthNativeConfigView.as_view()),
    path("api/auth/oauth/native/token", OAuthNativeTokenView.as_view()),
    path("api/users/self/ratings", UserRatingsView.as_view()),
    path("api/users/self/ratings/<uuid:recipe_id>", UserRatingView.as_view()),
    path("api/users/self/favorites", UserFavoritesView.as_view()),
    path("api/users/password", UserPasswordView.as_view()),
    path("api/users/<uuid:item_id>", UserUpdateView.as_view()),
    path("api/admin/about", AdminAboutView.as_view()),
    path("api/admin/about/statistics", AdminStatisticsView.as_view()),
    path("api/admin/about/check", AdminConfigView.as_view()),
    path("api/users/api-tokens", ApiTokenCreateView.as_view()),
    path("api/users/api-tokens/<str:token_id>", ApiTokenDeleteView.as_view()),
    path("api/auth/token", LoginView.as_view()),
    path("api/auth/refresh", RefreshView.as_view()),
    path("api/auth/logout", LogoutView.as_view()),
    path("api/users/self", UserSelfView.as_view()),
    path("api/app/about", AppInfoView.as_view()),
    path("api/app/about/startup-info", AppStartupInfoView.as_view()),
    path("api/app/about/theme", AppThemeView.as_view()),
]
