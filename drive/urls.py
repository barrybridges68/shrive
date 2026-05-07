from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "drive"

urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup_view, name="setup"),
    path("login/", views.login_view, name="login"),
    path("account/", views.account_view, name="account"),
    path("users/", views.admin_users, name="admin-users"),
    path("users/settings/", views.admin_settings, name="admin-settings"),
    path("users/stats/", views.admin_stats, name="admin-stats"),
    path("users/logs/", views.admin_logs, name="admin-logs"),
    path("users/logs/download/", views.admin_logs_download, name="admin-logs-download"),
    path("users/todo/", views.admin_todo, name="admin-todo"),
    path("logout/", LogoutView.as_view(next_page="drive:login"), name="logout"),
    path("shares/", views.my_shares, name="my-shares"),
    path("users/<int:user_id>/shares/", views.user_shares, name="user-shares"),
    path("space/", views.own_space, name="space"),
    path("space/download/", views.own_download, name="own-download"),
    path("space/open/", views.own_open, name="own-open"),
    path("space/thumb/", views.own_thumb, name="own-thumb"),
    path("shared/", views.shared_list, name="shared-list"),
    path("shared/<int:share_id>/", views.shared_browse, name="shared-browse"),
    path("shared/<int:share_id>/download/", views.shared_download, name="shared-download"),
    path("shared/<int:share_id>/open/", views.shared_open, name="shared-open"),
    path("shared/<int:share_id>/thumb/", views.shared_thumb, name="shared-thumb"),
    path("shared/group/<int:share_id>/", views.shared_group_browse, name="shared-group-browse"),
    path("shared/group/<int:share_id>/download/", views.shared_group_download, name="shared-group-download"),
    path("shared/group/<int:share_id>/open/", views.shared_group_open, name="shared-group-open"),
    path("shared/group/<int:share_id>/thumb/", views.shared_group_thumb, name="shared-group-thumb"),
    path("readonly/", views.readonly_list, name="readonly-list"),
    path("readonly/<slug:root_slug>/", views.readonly_browse, name="readonly-browse"),
    path("readonly/<slug:root_slug>/download/", views.readonly_download, name="readonly-download"),
    path("readonly/<slug:root_slug>/open/", views.readonly_open, name="readonly-open"),
    path("readonly/<slug:root_slug>/thumb/", views.readonly_thumb, name="readonly-thumb"),
    path("public/<str:token>/", views.public_browse, name="public-browse"),
    path("public/<str:token>/download/", views.public_download, name="public-download"),
    path("public/<str:token>/open/", views.public_open, name="public-open"),
    path("public/<str:token>/thumb/", views.public_thumb, name="public-thumb"),
]
