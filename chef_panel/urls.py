from django.urls import path
from . import views

app_name = 'chef_panel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/new/', views.new_orders, name='new_orders'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<int:order_id>/confirm/', views.confirm_order, name='confirm_order'),
    path('orders/<int:order_id>/ready/', views.mark_ready, name='mark_ready'),
    path('orders/<int:order_id>/cancel/', views.cancel_order, name='cancel_order'),
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/<int:product_id>/edit/', views.edit_product, name='edit_product'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.add_category, name='add_category'),
    
    # API endpoints
    path('api/orders/create/', views.create_order_api, name='create_order_api'),
    path('api/orders/update-status/', views.update_order_status, name='update_order_status'),
    path('api/orders/update-status-legacy/', views.update_order_status_api, name='update_order_status_api'),
    path('api/orders/<int:telegram_id>/user-orders/', views.get_user_orders_api, name='get_user_orders_api'),
    path('api/orders/<int:order_id>/details/', views.get_order_details_api, name='get_order_details_api'),
]
