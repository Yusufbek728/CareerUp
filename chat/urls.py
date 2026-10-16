from django.urls import path

from . import api, views

app_name = 'chat'

urlpatterns = [
    # Pages
    path('messages/', views.inbox, name='inbox'),
    path('messages/start/<str:listing_type>/<int:pk>/', views.start_conversation, name='start'),
    path('messages/<int:pk>/', views.conversation_detail, name='conversation'),
    path('messages/<int:pk>/send/', views.send_message, name='send'),
    path('messages/<int:pk>/block/', views.block_user, name='block'),
    path('messages/<int:pk>/unblock/', views.unblock_user, name='unblock'),
    path('messages/report/<int:message_id>/', views.report_message, name='report'),
    path('messages/attachment/<int:message_id>/', views.attachment_download, name='attachment'),
    # REST API
    path('api/conversations/', api.ConversationListCreateView.as_view(), name='api-conversation-list'),
    path('api/conversations/<int:pk>/', api.ConversationDetailView.as_view(), name='api-conversation-detail'),
    path('api/conversations/<int:pk>/messages/', api.ConversationMessagesView.as_view(), name='api-conversation-messages'),
    path('api/conversations/<int:pk>/read/', api.ConversationReadView.as_view(), name='api-conversation-read'),
    path('api/messages/<int:pk>/attachment/', api.MessageAttachmentView.as_view(), name='api-message-attachment'),
    path('api/blocks/', api.BlockListCreateView.as_view(), name='api-block-list'),
    path('api/blocks/<int:pk>/', api.BlockDeleteView.as_view(), name='api-block-detail'),
    path('api/reports/', api.ReportListCreateView.as_view(), name='api-report-list'),
]
