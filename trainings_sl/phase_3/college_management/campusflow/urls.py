from django.urls import path

from campus import views


urlpatterns = [
    path("", views.index),
    path("api/session", views.session_info),
    path("api/login", views.login),
    path("api/signup", views.signup),
    path("api/logout", views.logout),
    path("api/dashboard", views.dashboard),
    path("api/chatbot", views.chatbot),
    path("api/knowledge", views.knowledge),
    path("api/knowledge/<int:document_id>", views.knowledge_detail),
    path("api/export/<str:resource>", views.export_resource),
    path("api/<str:resource>", views.collection),
    path("api/<str:resource>/<int:record_id>", views.detail),
]

handler400 = "campus.views.bad_request"
handler403 = "campus.views.permission_denied"
handler404 = "campus.views.not_found"
handler500 = "campus.views.server_error"
