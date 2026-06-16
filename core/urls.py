from django.urls import path
from core import views

app_name = "core"

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Protocols
    path("protocols/", views.protocol_list, name="protocol_list"),
    path("protocols/list-body/", views.protocol_list_body, name="protocol_list_body"),
    path("protocols/new/", views.protocol_create, name="protocol_create"),
    path("protocols/<uuid:pk>/edit/", views.protocol_edit_view, name="protocol_edit"),
    path("protocols/<uuid:pk>/create-from/", views.protocol_create_from, name="protocol_create_from"),
    path("protocols/<uuid:pk>/delete/", views.protocol_delete, name="protocol_delete"),
    path("protocols/<uuid:pk>/view/", views.protocol_view, name="protocol_view"),
    path("protocols/<uuid:pk>/print-choose/", views.protocol_print_choose, name="protocol_print_choose"),
    path("protocols/<uuid:pk>/save-as-template/", views.protocol_save_as_template, name="protocol_save_as_template"),
    path("protocols/preview/", views.protocol_preview, name="protocol_preview"),
    path("protocols/save-action/", views.protocol_save_action, name="protocol_save_action"),
    path("protocols/<uuid:pk>/print/", views.protocol_print, name="protocol_print"),
    path("protocols/<uuid:pk>.pdf", views.protocol_pdf, name="protocol_pdf"),

    # Templates
    path("templates/", views.template_list, name="template_list"),
    path("templates/<uuid:folder_id>/", views.template_list, name="template_folder"),

    # Folder CRUD
    path("folders/create/", views.folder_create, name="folder_create"),
    path("folders/<uuid:pk>/edit/", views.folder_edit, name="folder_edit"),
    path("folders/<uuid:pk>/delete/", views.folder_delete, name="folder_delete"),

    # Template actions
    path("templates/<uuid:pk>/use/", views.template_use, name="template_use"),
    path("templates/<uuid:pk>/move/", views.template_move, name="template_move"),
    path("templates/<uuid:pk>/edit/", views.template_edit_view, name="template_edit"),
    path("templates/<uuid:pk>/delete/", views.template_delete, name="template_delete"),

    # Clients
    path("clients/", views.client_list, name="client_list"),
    path("clients/create/", views.client_create, name="client_create"),
    path("clients/<uuid:pk>/edit/", views.client_edit, name="client_edit"),
    path("clients/<uuid:pk>/delete/", views.client_delete, name="client_delete"),
    path("clients/<uuid:pk>/sites-section/", views.sites_section, name="sites_section"),

    # Sites (within clients accordion)
    path("clients/<uuid:client_pk>/sites/create/", views.site_create, name="site_create"),

    # Sites (standalone Обекти page)
    path("sites/", views.site_list, name="site_list"),
    path("sites/list-body/", views.site_list_body, name="site_list_body"),
    path("sites/create/", views.site_create_full, name="site_create_full"),
    path("sites/<uuid:pk>/edit/", views.site_edit, name="site_edit"),
    path("sites/<uuid:pk>/delete/", views.site_delete, name="site_delete"),

    # Site contacts
    path("sites/<uuid:site_pk>/contacts/", views.site_contacts, name="site_contacts"),
    path("sites/<uuid:site_pk>/contacts/create/", views.site_contact_create, name="site_contact_create"),
    path("contacts/<uuid:pk>/delete/", views.site_contact_delete, name="site_contact_delete"),
    path("contacts/<uuid:pk>/move/<str:direction>/", views.site_contact_move, name="site_contact_move"),

    # Tags (Етикети)
    path("tags/", views.tag_list, name="tag_list"),
    path("tags/create/", views.tag_create, name="tag_create"),
    path("tags/<uuid:pk>/edit/", views.tag_edit, name="tag_edit"),
    path("tags/<uuid:pk>/delete-confirm/", views.tag_delete_confirm, name="tag_delete_confirm"),
    path("tags/<uuid:pk>/delete/", views.tag_delete, name="tag_delete"),
    path("tags/reorder/", views.tag_reorder, name="tag_reorder"),

    # Препарати (Stage 3a)
    path("products/", views.product_list, name="product_list"),
    path("products/list-body/", views.product_list_body, name="product_list_body"),
    path("products/create/", views.product_create, name="product_create"),
    path("products/<uuid:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<uuid:pk>/delete/", views.product_delete, name="product_delete"),

    # Фирми (Stage 3b)
    path("companies/", views.company_list, name="company_list"),
    path("companies/cards/", views.company_cards, name="company_cards"),
    path("companies/create/", views.company_create, name="company_create"),
    path("companies/<uuid:pk>/edit/", views.company_edit, name="company_edit"),
    path("companies/<uuid:pk>/set-default/", views.company_set_default, name="company_set_default"),
    path("companies/<uuid:pk>/delete/", views.company_delete, name="company_delete"),
    path("companies/reorder/", views.company_reorder, name="company_reorder"),

    # Работници (Stage 3b)
    path("workers/", views.worker_list, name="worker_list"),
    path("workers/list-body/", views.worker_list_body, name="worker_list_body"),
    path("workers/create/", views.worker_create, name="worker_create"),
    path("workers/<uuid:pk>/edit/", views.worker_edit, name="worker_edit"),
    path("workers/<uuid:pk>/delete/", views.worker_delete, name="worker_delete"),

    # Настройки (Stage 4)
    path("settings/", views.settings_view, name="settings"),
    path("settings/save/", views.settings_save, name="settings_save"),

    # База данни — OneDrive/backup sync (Stage 6a/6b)
    path("database/", views.database_view, name="database"),
    path("database/save/", views.database_save, name="database_save"),
    path("database/sync-now/", views.database_sync_now, name="database_sync_now"),
    path("sync/conflict/", views.sync_conflict, name="sync_conflict"),

    # Вредители (Stage 3c)
    path("pests/", views.pest_list, name="pest_list"),
    path("pests/list-body/", views.pest_list_body, name="pest_list_body"),
    path("pests/create/", views.pest_create, name="pest_create"),
    path("pests/<uuid:pk>/edit/", views.pest_edit, name="pest_edit"),
    path("pests/<uuid:pk>/delete/", views.pest_delete, name="pest_delete"),

    # Нехимични средства (Stage 3c)
    path("nonchemical/", views.nonchemical_list, name="nonchemical_list"),
    path("nonchemical/list-body/", views.nonchemical_list_body, name="nonchemical_list_body"),
    path("nonchemical/create/", views.nonchemical_create, name="nonchemical_create"),
    path("nonchemical/<uuid:pk>/edit/", views.nonchemical_edit, name="nonchemical_edit"),
    path("nonchemical/<uuid:pk>/delete/", views.nonchemical_delete, name="nonchemical_delete"),

    # Еднократни обработки
    path("one-time/", views.one_time_list, name="one_time_list"),
    path("one-time/create/", views.one_time_create, name="one_time_create"),
    path("one-time/<uuid:pk>/edit/", views.one_time_edit, name="one_time_edit"),
    path("one-time/<uuid:pk>/delete-confirm/", views.one_time_delete_confirm, name="one_time_delete_confirm"),
    path("one-time/<uuid:pk>/delete/", views.one_time_delete, name="one_time_delete"),
]