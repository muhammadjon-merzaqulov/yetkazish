from django.urls import path
from . import views

app_name = 'chef_panel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/new/', views.new_orders, name='new_orders'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/edit/<int:product_id>/', views.edit_product, name='edit_product'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.add_category, name='add_category'),

    # API endpoints
    path('api/create_order/', views.create_order_api, name='create_order_api'),
    path('api/update_order_status/', views.update_order_status_api, name='update_order_status_api'),
    path('api/get_user_orders/<str:telegram_id>/', views.get_user_orders_api, name='get_user_orders_api'),
    path('api/order/<int:order_id>/details/', views.get_order_details_api, name='get_order_details_api'), # New API endpoint
    
    # Action endpoints
    path('orders/<int:order_id>/confirm/', views.confirm_order, name='confirm_order'),
    path('orders/<int:order_id>/ready/', views.mark_ready, name='mark_ready'),
    path('orders/<int:order_id>/cancel/', views.cancel_order, name='cancel_order'),
]
