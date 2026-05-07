from django.contrib import admin
from django.urls import include, path

from drive import views as drive_views

urlpatterns = [
    path('admin/users/', drive_views.admin_users, name='admin-users-legacy'),
    path('admin/users/stats/', drive_views.admin_stats, name='admin-stats-legacy'),
    path('admin/users/todo/', drive_views.admin_todo, name='admin-todo-legacy'),
    path('admin/', admin.site.urls),
    path('', include('drive.urls')),
]
