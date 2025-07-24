from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count, Q, Sum
from django.core.paginator import Paginator
import json
import logging
from datetime import timedelta

from django.conf import settings
from .utils import send_telegram_message, send_telegram_location
from .models import Order, Product, Category, OrderItem, OrderStatusHistory, Customer
from .forms import ProductForm, CategoryForm

logger = logging.getLogger(__name__)

def dashboard(request):
    """Oshpaz dashboard"""
    # Statistika
    today = timezone.now().date()
    
    stats = {
        'yangi_buyurtmalar': Order.objects.filter(status='yangi').count(),
        'tasdiqlangan_buyurtmalar': Order.objects.filter(status='tasdiqlangan').count(),
        'tayor_buyurtmalar': Order.objects.filter(status='tayor').count(),
        'bugungi_buyurtmalar': Order.objects.filter(created_at__date=today).count(),
        'pickup_buyurtmalar': Order.objects.filter(service_type='pickup', status__in=['yangi', 'tasdiqlangan', 'tayor']).count(),
        'delivery_buyurtmalar': Order.objects.filter(service_type='delivery', status__in=['yangi', 'tasdiqlangan', 'tayor', 'yolda']).count(),
    }
    
    # Oxirgi buyurtmalar
    recent_orders = Order.objects.filter(
        Q(status__in=['yangi', 'tasdiqlangan']) |
        Q(status='tayor', service_type='pickup')
    ).order_by('-created_at')[:10]
    
    # Mijozlar statistikasi: eng ko'p buyurtma bergan mijozlar
    top_customers = Customer.objects.annotate(
        order_count=Count('order')
    ).order_by('-order_count')[:10]

    # Haftalik buyurtmalar statistikasi
    seven_days_ago = timezone.now() - timedelta(days=7)
    weekly_orders_queryset = Order.objects.filter(created_at__gte=seven_days_ago)
    
    weekly_stats = {
        'total_orders': weekly_orders_queryset.count(),
        'total_amount': weekly_orders_queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
        'pickup_orders': weekly_orders_queryset.filter(service_type='pickup').count(),
        'delivery_orders': weekly_orders_queryset.filter(service_type='delivery').count(),
    }

    # Bugungi umumiy savdo
    today_sales = Order.objects.filter(created_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # Holatlar bo'yicha savdo
    sales_by_status = Order.objects.values('status').annotate(total_sales=Sum('total_amount')).order_by('status')
    
    # Status nomlarini olish uchun lug'at yaratamiz
    status_display_map = dict(Order.STATUS_CHOICES)
    sales_by_status_display = []
    for item in sales_by_status:
        sales_by_status_display.append({
            'status': status_display_map.get(item['status'], item['status']),
            'total_sales': item['total_sales']
        })

    # Service type bo'yicha statistika
    service_stats = Order.objects.values('service_type').annotate(
        total_orders=Count('id'),
        total_sales=Sum('total_amount')
    ).order_by('service_type')
    
    service_display_map = dict(Order.SERVICE_TYPE_CHOICES)
    service_stats_display = []
    for item in service_stats:
        service_stats_display.append({
            'service_type': service_display_map.get(item['service_type'], item['service_type']),
            'total_orders': item['total_orders'],
            'total_sales': item['total_sales']
        })

    context = {
        'stats': stats,
        'recent_orders': recent_orders,
        'top_customers': top_customers,
        'weekly_stats': weekly_stats,
        'today_sales': today_sales,
        'sales_by_status': sales_by_status_display,
        'service_stats': service_stats_display,
    }
    return render(request, 'chef_panel/dashboard.html', context)

def order_list(request):
    """Barcha buyurtmalar ro'yxati"""
    status_filter = request.GET.get('status', '')
    service_type_filter = request.GET.get('service_type', '')
    search = request.GET.get('search', '')
    
    orders = Order.objects.all().order_by('-created_at')
    
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    if service_type_filter:
        orders = orders.filter(service_type=service_type_filter)
    
    if search:
        orders = orders.filter(
            Q(order_number__icontains=search) |
            Q(customer__full_name__icontains=search) |
            Q(customer__phone_number__icontains=search)
        )
    
    paginator = Paginator(orders, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'service_type_filter': service_type_filter,
        'search': search,
        'status_choices': Order.STATUS_CHOICES,
        'service_type_choices': Order.SERVICE_TYPE_CHOICES,
    }
    return render(request, 'chef_panel/order_list.html', context)

def new_orders(request):
    """Yangi buyurtmalar - pickup buyurtmalar olib ketilmaguncha ko'rinadi"""
    orders = Order.objects.filter(
        Q(status__in=['yangi', 'tasdiqlangan']) |
        Q(status='tayor', service_type='pickup')
    ).order_by('-created_at')
    
    context = {
        'orders': orders,
        'title': 'Yangi buyurtmalar',
    }
    return render(request, 'chef_panel/new_orders.html', context)

def order_detail(request, order_id):
    """Buyurtma tafsilotlari"""
    order = get_object_or_404(Order, id=order_id)
    order_items = order.items.all()
    status_history = order.status_history.all()
    
    context = {
        'order': order,
        'order_items': order_items,
        'status_history': status_history,
    }
    return render(request, 'chef_panel/order_detail.html', context)

@csrf_exempt
def create_order_api(request):
    """Telegram botdan yangi buyurtma qabul qilish API"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Mijozni topish yoki yaratish
            telegram_id = data.get('user_id')
            full_name = data.get('full_name', 'Noma\'lum')
            phone_number = data.get('phone', 'Noma\'lum')
            
            customer, created = Customer.objects.get_or_create(
                telegram_id=telegram_id,
                defaults={'full_name': full_name, 'phone_number': phone_number}
            )
            if not created:
                # Agar mijoz mavjud bo'lsa, ma'lumotlarini yangilash
                customer.full_name = full_name
                customer.phone_number = phone_number
                customer.save()

            # Buyurtma yaratish
            order = Order.objects.create(
                customer=customer,
                telegram_user_id=telegram_id,
                status='yangi',
                payment_method=data.get('payment_method', 'naqd'),
                service_type=data.get('service_type', 'delivery'),
                latitude=data.get('location', {}).get('latitude') if data.get('service_type') == 'delivery' else None,
                longitude=data.get('location', {}).get('longitude') if data.get('service_type') == 'delivery' else None,
                address=data.get('address', '') if data.get('service_type') == 'delivery' else None,
                products_total=data.get('products_total'),
                delivery_cost=data.get('delivery_cost', 0),
                total_amount=data.get('total'),
            )

            # Buyurtma elementlarini qo'shish
            for item_data in data.get('products', []):
                product_name, quantity, item_price = item_data
                product = Product.objects.filter(name=product_name).first()
                if product:
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price=item_price,
                        total=quantity * item_price
                    )
                else:
                    logger.warning(f"Mahsulot topilmadi: {product_name} (Buyurtma ID: {order.id})")

            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status='',
                new_status='yangi',
                notes='Telegram bot orqali yaratildi'
            )

            # Oshpazga xabar yuborish
            chef_text = f"🍽 **Yangi buyurtma #{order.order_number}**\n\n"
            chef_text += f"👨‍💼 Ism: {full_name}\n"
            chef_text += f"📱 Telefon: {phone_number}\n"
            chef_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
            chef_text += f"🚀 Xizmat turi: {order.get_service_type_display()}\n"
            
            if order.service_type == 'delivery':
                if order.address:
                    chef_text += f"🏠 Manzil: {order.address}\n"
                else:
                    chef_text += "📍 Manzil: Faqat lokatsiya\n"
            else:
                chef_text += "🏪 Olib ketish uchun: Restoranidan\n"
                
            chef_text += f"\n🍽 **Mahsulotlar:**\n"
            for item in order.items.all():
                chef_text += f"• {item.quantity} dona {item.product.name} - {item.total:,} so'm\n"
            chef_text += f"\n💰 Jami: {order.total_amount:,} so'm"

            keyboard_chef = [
                [
                    {'text': "✅ Tasdiqlash", 'callback_data': f"chef_confirm:{order.id}"},
                    {'text': "❌ Bekor qilish", 'callback_data': f"chef_cancel:{order.id}"}
                ]
            ]
            
            chef_msg_response = send_telegram_message(
                chat_id=settings.CHEF_CHAT_ID, 
                text=chef_text, 
                reply_markup={'inline_keyboard': keyboard_chef}
            )
            if chef_msg_response and chef_msg_response.get('ok'):
                order.chef_message_id = chef_msg_response['result']['message_id']
            
            # Lokatsiya yuborish faqat delivery uchun
            if order.service_type == 'delivery' and order.latitude and order.longitude:
                send_telegram_location(
                    chat_id=settings.CHEF_CHAT_ID,
                    latitude=order.latitude,
                    longitude=order.longitude
                )

            # Foydalanuvchiga xabar
            user_text = f"✅ **Buyurtmangiz qabul qilindi!**\n\n"
            user_text += f"📋 Buyurtma ID: **{order.order_number}**\n"
            user_text += f"👨‍💼 Ism: {full_name}\n"
            user_text += f"📱 Telefon: {phone_number}\n"
            user_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
            user_text += f"🚀 Xizmat turi: {order.get_service_type_display()}\n"
            
            if order.service_type == 'delivery':
                if order.address:
                    user_text += f"🏠 Manzil: {order.address}\n"
                else:
                    user_text += "📍 Manzil: Faqat lokatsiya\n"
                if order.latitude and order.longitude:
                    user_text += f"📍 Lokatsiya: https://www.google.com/maps?q={order.latitude},{order.longitude}\n"
            else:
                user_text += "🏪 Olib ketish uchun: Restoranidan\n"
                
            user_text += f"\n🍽 **Mahsulotlar:**\n"
            for item in order.items.all():
                user_text += f"• {item.quantity} dona {item.product.name} - {item.total:,} so'm\n"
            user_text += f"\n💰 Jami: {order.total_amount:,} so'm\n🆕 Status: **Yangi**"

            user_keyboard = [[{'text': "⬅️ Bosh menu", 'callback_data': "main_menu"}]]
            user_msg_response = send_telegram_message(
                chat_id=telegram_id,
                text=user_text,
                reply_markup={'inline_keyboard': user_keyboard}
            )
            if user_msg_response and user_msg_response.get('ok'):
                order.user_message_id = user_msg_response['result']['message_id']
            
            order.save() # Save message IDs

            return JsonResponse({'success': True, 'order_id': order.id, 'order_number': order.order_number})
        except Exception as e:
            logger.error(f"Buyurtma yaratishda xato: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': 'Faqat POST so\'rov qabul qilinadi'}, status=405)

def _update_telegram_messages(order, old_status, new_status, changed_by_user=None):
    """Buyurtma holati o'zgarganda Telegram xabarlarini yangilash"""
    status_emoji = {
        "yangi": "🆕",
        "tasdiqlangan": "✅",
        "tayor": "🍽",
        "yolda": "🚚",
        "yetkazildi": "✅",
        "olib_ketildi": "✅",
        "bekor_qilingan": "❌"
    }
    emoji = status_emoji.get(new_status, "📋")

    # Foydalanuvchi xabarini yangilash
    user_text = f"✅ **Buyurtmangiz qabul qilindi!**\n\n"
    user_text += f"📋 Buyurtma ID: **{order.order_number}**\n"
    user_text += f"👨‍💼 Ism: {order.customer.full_name}\n"
    user_text += f"📱 Telefon: {order.customer.phone_number}\n"
    user_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
    user_text += f"🚀 Xizmat turi: {order.get_service_type_display()}\n"
    
    if order.service_type == 'delivery':
        if order.address:
            user_text += f"🏠 Manzil: {order.address}\n"
        else:
            user_text += "📍 Manzil: Faqat lokatsiya\n"
        if order.latitude and order.longitude:
            user_text += f"📍 Lokatsiya: https://www.google.com/maps?q={order.latitude},{order.longitude}\n"
    else:
        user_text += "🏪 Olib ketish uchun: Restoranidan\n"
        
    user_text += f"\n🍽 **Mahsulotlar:**\n"
    for item in order.items.all():
        user_text += f"• {item.quantity} dona {item.product.name} - {item.total:,} so'm\n"
    user_text += f"\n💰 Jami: {order.total_amount:,} so'm\n"
    user_text += f"{emoji} Status: **{order.get_status_display()}**"

    user_keyboard = [[{'text': "⬅️ Bosh menu", 'callback_data': "main_menu"}]]
    
    if order.user_message_id and order.telegram_user_id:
        send_telegram_message(
            chat_id=order.telegram_user_id,
            text=user_text,
            reply_markup={'inline_keyboard': user_keyboard},
            message_id=order.user_message_id
        )
    else:
        # Agar message_id yo'q bo'lsa, yangi xabar yuborish
        if order.telegram_user_id:
            response = send_telegram_message(
                chat_id=order.telegram_user_id,
                text=user_text,
                reply_markup={'inline_keyboard': user_keyboard}
            )
            if response and response.get('ok'):
                order.user_message_id = response['result']['message_id']
                order.save()

    # Oshpaz xabarini yangilash
    if order.chef_message_id:
        chef_text = f"{emoji} **Buyurtma #{order.order_number} holati o'zgardi: {order.get_status_display()}**\n\n"
        chef_text += f"👨‍💼 Ism: {order.customer.full_name}\n"
        chef_text += f"📱 Telefon: {order.customer.phone_number}\n"
        chef_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
        chef_text += f"🚀 Xizmat turi: {order.get_service_type_display()}\n"
        
        if order.service_type == 'delivery':
            if order.address:
                chef_text += f"🏠 Manzil: {order.address}\n"
            else:
                chef_text += "📍 Manzil: Faqat lokatsiya\n"
        else:
            chef_text += "🏪 Olib ketish uchun: Restoranidan\n"
            
        chef_text += f"\n🍽 **Mahsulotlar:**\n"
        for item in order.items.all():
            chef_text += f"• {item.quantity} dona {item.product.name} - {item.total:,} so'm\n"
        chef_text += f"\n💰 Jami: {order.total_amount:,} so'm"

        chef_keyboard = []
        if new_status == 'yangi':
            chef_keyboard = [
                [{'text': "✅ Tasdiqlash", 'callback_data': f"chef_confirm:{order.id}"},
                 {'text': "❌ Bekor qilish", 'callback_data': f"chef_cancel:{order.id}"}]
            ]
        elif new_status == 'tasdiqlangan':
            chef_keyboard = [
                [{'text': "🍽 Tayor", 'callback_data': f"chef_ready:{order.id}"}],
                [{'text': "❌ Bekor qilish", 'callback_data': f"chef_cancel:{order.id}"}]
            ]
        elif new_status == 'tayor' and order.service_type == 'pickup':
            chef_keyboard = [
                [{'text': "✅ Olib ketildi", 'callback_data': f"chef_picked_up:{order.id}"}],
                [{'text': "❌ Bekor qilish", 'callback_data': f"chef_cancel:{order.id}"}]
            ]
        # If status is 'tayor' (delivery), 'yolda', 'yetkazildi', 'olib_ketildi', 'bekor_qilingan', no more actions for chef
        
        send_telegram_message(
            chat_id=settings.CHEF_CHAT_ID,
            text=chef_text,
            reply_markup={'inline_keyboard': chef_keyboard},
            message_id=order.chef_message_id
        )

    # Kuryer xabarini yangilash (faqat delivery uchun)
    if order.service_type == 'delivery':
        if order.courier_message_id:
            courier_text = f"{emoji} **Buyurtma #{order.order_number} holati o'zgardi: {order.get_status_display()}**\n\n"
            courier_text += f"👨‍💼 Ism: {order.customer.full_name}\n"
            courier_text += f"📱 Telefon: {order.customer.phone_number}\n"
            courier_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
            if order.address:
                courier_text += f"🏠 Manzil: {order.address}\n"
            else:
                courier_text += "📍 Manzil: Faqat lokatsiya\n"
            courier_text += f"\n🍽 **Mahsulotlar:**\n"
            for item in order.items.all():
                courier_text += f"• {item.quantity} dona {item.product.name} - {item.total:,} so'm\n"
            courier_text += f"\n💰 Jami: {order.total_amount:,} so'm"

            courier_keyboard = []
            if new_status == 'tayor':
                courier_keyboard = [
                    [{'text': "🚚 Yo'lda", 'callback_data': f"courier_on_way:{order.id}"}],
                    [{'text': "❌ Bekor qilish", 'callback_data': f"courier_cancel:{order.id}"}]
                ]
            elif new_status == 'yolda':
                courier_keyboard = [
                    [{'text': "✅ Yetkazildi", 'callback_data': f"courier_delivered:{order.id}"}],
                    [{'text': "❌ Bekor qilish", 'callback_data': f"courier_cancel:{order.id}"}]
                ]
            
            send_telegram_message(
                chat_id=settings.ADMIN_CHAT_ID, # Assuming ADMIN_CHAT_ID is courier's chat ID
                text=courier_text,
                reply_markup={'inline_keyboard': courier_keyboard},
                message_id=order.courier_message_id
            )
        elif new_status == 'tayor': # If order is ready, send new message to courier if no existing message_id
            courier_text = f"🚚 **Yetkazib berish uchun yangi buyurtma #{order.order_number}**\n\n"
            courier_text += f"👨‍💼 Ism: {order.customer.full_name}\n"
            courier_text += f"📱 Telefon: {order.customer.phone_number}\n"
            courier_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
            if order.address:
                courier_text += f"🏠 Manzil: {order.address}\n"
            else:
                courier_text += "📍 Manzil: Faqat lokatsiya\n"
            courier_text += f"\n🍽 **Mahsulotlar:**\n"
            for item in order.items.all():
                courier_text += f"• {item.quantity} dona {item.product.name} - {item.total:,} so'm\n"
            courier_text += f"\n💰 Jami: {order.total_amount:,} so'm"

            courier_keyboard = [
                [{'text': "🚚 Yo'lda", 'callback_data': f"courier_on_way:{order.id}"}],
                [{'text': "❌ Bekor qilish", 'callback_data': f"courier_cancel:{order.id}"}]
            ]
            courier_msg_response = send_telegram_message(
                chat_id=settings.ADMIN_CHAT_ID,
                text=courier_text,
                reply_markup={'inline_keyboard': courier_keyboard}
            )
            if courier_msg_response and courier_msg_response.get('ok'):
                order.courier_message_id = courier_msg_response['result']['message_id']
                order.save()
            
            if order.latitude and order.longitude:
                send_telegram_location(
                    chat_id=settings.ADMIN_CHAT_ID,
                    latitude=order.latitude,
                    longitude=order.longitude
                )

@csrf_exempt
def update_order_status(request):
    """Buyurtma holatini yangilash API"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data.get('order_id')
            new_status = data.get('status')
            
            order = get_object_or_404(Order, id=order_id)
            old_status = order.status
            
            # Valid transitions for different service types
            if order.service_type == 'pickup':
                valid_transitions = {
                    'yangi': ['tasdiqlangan', 'bekor_qilingan'],
                    'tasdiqlangan': ['tayor', 'bekor_qilingan'],
                    'tayor': ['olib_ketildi', 'bekor_qilingan'],
                }
            else:  # delivery
                valid_transitions = {
                    'yangi': ['tasdiqlangan', 'bekor_qilingan'],
                    'tasdiqlangan': ['tayor', 'bekor_qilingan'],
                    'tayor': ['yolda', 'bekor_qilingan'],
                    'yolda': ['yetkazildi', 'bekor_qilingan'],
                }

            if new_status not in valid_transitions.get(old_status, []):
                return JsonResponse({
                    'success': False, 
                    'message': f'Holat {old_status} dan {new_status} ga o\'zgartirishga ruxsat berilmagan.'
                }, status=400)
            
            # Holatni yangilash
            order.status = new_status
            
            # Vaqt belgilarini yangilash
            if new_status == 'tasdiqlangan':
                order.confirmed_at = timezone.now()
            elif new_status == 'tayor':
                order.ready_at = timezone.now()
            elif new_status == 'yetkazildi':
                order.delivered_at = timezone.now()
            elif new_status == 'olib_ketildi':
                order.picked_up_at = timezone.now()
            
            order.save()
            
            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status=new_status,
                changed_by=request.user if request.user.is_authenticated else None,
                notes=f'Web panel orqali yangilandi'
            )
            
            # Telegram xabarlarini yangilash
            _update_telegram_messages(order, old_status, new_status, request.user)
            
            return JsonResponse({
                'success': True, 
                'message': f'Buyurtma holati {old_status} dan {new_status} ga o\'zgartirildi.'
            })
        except Exception as e:
            logger.error(f"Buyurtma holatini yangilashda xato: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False, 'message': 'Faqat POST so\'rov qabul qilinadi'}, status=405)

@csrf_exempt
def confirm_order(request, order_id):
    """Buyurtmani tasdiqlash"""
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        
        if order.status == 'yangi':
            old_status = order.status
            order.status = 'tasdiqlangan'
            order.confirmed_at = timezone.now()
            order.save()
            
            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status='tasdiqlangan',
                changed_by=request.user if request.user.is_authenticated else None,
                notes='Oshpaz tomonidan tasdiqlandi'
            )
            
            _update_telegram_messages(order, old_status, 'tasdiqlangan', request.user)
            
            messages.success(request, f'Buyurtma #{order.order_number} tasdiqlandi!')
            return JsonResponse({'success': True, 'message': 'Buyurtma tasdiqlandi'})
        else:
            return JsonResponse({'success': False, 'message': 'Buyurtma allaqachon tasdiqlangan'})
    
    return JsonResponse({'success': False, 'message': 'Noto\'g\'ri so\'rov'})

@csrf_exempt
def mark_ready(request, order_id):
    """Buyurtmani tayor deb belgilash"""
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        
        if order.status == 'tasdiqlangan':
            old_status = order.status
            order.status = 'tayor'
            order.ready_at = timezone.now()
            order.save()
            
            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status='tayor',
                changed_by=request.user if request.user.is_authenticated else None,
                notes='Oshpaz tomonidan tayor deb belgilandi'
            )
            
            _update_telegram_messages(order, old_status, 'tayor', request.user)
            
            messages.success(request, f'Buyurtma #{order.order_number} tayor!')
            return JsonResponse({'success': True, 'message': 'Buyurtma tayor'})
        else:
            return JsonResponse({'success': False, 'message': 'Buyurtma avval tasdiqlanishi kerak'})
    
    return JsonResponse({'success': False, 'message': 'Noto\'g\'ri so\'rov'})

@csrf_exempt
def mark_picked_up(request, order_id):
    """Pickup buyurtmani olib ketildi deb belgilash"""
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        
        if order.status == 'tayor' and order.service_type == 'pickup':
            old_status = order.status
            order.status = 'olib_ketildi'
            order.picked_up_at = timezone.now()
            order.save()
            
            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status='olib_ketildi',
                changed_by=request.user if request.user.is_authenticated else None,
                notes='Oshpaz tomonidan olib ketildi deb belgilandi'
            )
            
            _update_telegram_messages(order, old_status, 'olib_ketildi', request.user)
            
            messages.success(request, f'Buyurtma #{order.order_number} olib ketildi!')
            return JsonResponse({'success': True, 'message': 'Buyurtma olib ketildi'})
        else:
            return JsonResponse({'success': False, 'message': 'Buyurtma tayor holatida bo\'lishi va pickup turi bo\'lishi kerak'})
    
    return JsonResponse({'success': False, 'message': 'Noto\'g\'ri so\'rov'})

@csrf_exempt
def cancel_order(request, order_id):
    """Buyurtmani bekor qilish"""
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        
        if order.status not in ['yetkazildi', 'olib_ketildi', 'bekor_qilingan']:
            old_status = order.status
            order.status = 'bekor_qilingan'
            order.save()
            
            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status='bekor_qilingan',
                changed_by=request.user if request.user.is_authenticated else None,
                notes='Oshpaz tomonidan bekor qilindi'
            )
            
            _update_telegram_messages(order, old_status, 'bekor_qilingan', request.user)
            
            messages.success(request, f'Buyurtma #{order.order_number} bekor qilindi!')
            return JsonResponse({'success': True, 'message': 'Buyurtma bekor qilindi'})
        else:
            return JsonResponse({'success': False, 'message': 'Bu buyurtmani bekor qilib bo\'lmaydi'})
    
    return JsonResponse({'success': False, 'message': 'Noto\'g\'ri so\'rov'})

# Mahsulotlar boshqaruvi
def product_list(request):
    """Mahsulotlar ro'yxati"""
    products = Product.objects.all().order_by('category', 'name')
    categories = Category.objects.filter(is_active=True)
    
    category_filter = request.GET.get('category')
    if category_filter:
        products = products.filter(category_id=category_filter)
    
    context = {
        'products': products,
        'categories': categories,
        'selected_category': int(category_filter) if category_filter else None,
    }
    return render(request, 'chef_panel/product_list.html', context)

def add_product(request):
    """Yangi mahsulot qo'shish"""
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Mahsulot muvaffaqiyatli qo\'shildi!')
            return redirect('chef_panel:product_list')
    else:
        form = ProductForm()
    return render(request, 'chef_panel/add_product.html', {'form': form})

def edit_product(request, product_id):
    """Mahsulotni tahrirlash"""
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Mahsulot muvaffaqiyatli yangilandi!')
            return redirect('chef_panel:product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'chef_panel/edit_product.html', {'form': form, 'product': product})

# Kategoriyalar boshqaruvi
def category_list(request):
    """Kategoriyalar ro'yxati"""
    categories = Category.objects.all().order_by('name')
    return render(request, 'chef_panel/category_list.html', {'categories': categories})

def add_category(request):
    """Yangi kategoriya qo'shish"""
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Kategoriya muvaffaqiyatli qo\'shildi!')
            return redirect('chef_panel:category_list')
    else:
        form = CategoryForm()
    return render(request, 'chef_panel/add_category.html', {'form': form})

@csrf_exempt
def update_order_status_api(request):
    """API: Buyurtma holatini yangilash (Telegram botdan keladigan so'rovlar uchun)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data.get('order_id')
            new_status = data.get('status')
            
            order = get_object_or_404(Order, id=order_id)
            old_status = order.status
            
            # Valid transitions for different service types
            if order.service_type == 'pickup':
                valid_transitions = {
                    'yangi': ['tasdiqlangan', 'bekor_qilingan'],
                    'tasdiqlangan': ['tayor', 'bekor_qilingan'],
                    'tayor': ['olib_ketildi', 'bekor_qilingan'],
                }
            else:  # delivery
                valid_transitions = {
                    'yangi': ['tasdiqlangan', 'bekor_qilingan'],
                    'tasdiqlangan': ['tayor', 'bekor_qilingan'],
                    'tayor': ['yolda', 'bekor_qilingan'],
                    'yolda': ['yetkazildi', 'bekor_qilingan'],
                }

            if new_status not in valid_transitions.get(old_status, []):
                return JsonResponse({'success': False, 'message': f"Holat {old_status} dan {new_status} ga o'zgartirishga ruxsat berilmagan."}, status=400)

            order.status = new_status
            
            # Vaqt belgilarini yangilash
            if new_status == 'tasdiqlangan':
                order.confirmed_at = timezone.now()
            elif new_status == 'tayor':
                order.ready_at = timezone.now()
            elif new_status == 'yetkazildi':
                order.delivered_at = timezone.now()
            elif new_status == 'olib_ketildi':
                order.picked_up_at = timezone.now()
            
            order.save()
            
            # Holat tarixini saqlash
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status=new_status,
                notes=f'Telegram bot orqali yangilandi'
            )
            
            _update_telegram_messages(order, old_status, new_status) # Update messages after status change
            
            return JsonResponse({
                'success': True, 
                'message': f'Buyurtma holati {new_status}ga o\'zgartirildi'
            })
            
        except Exception as e:
            logger.error(f"API orqali buyurtma holatini yangilashda xato: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'message': 'Faqat POST so\'rov qabul qilinadi'}, status=405)

@csrf_exempt
def get_user_orders_api(request, telegram_id):
    """API: Foydalanuvchining buyurtmalarini olish"""
    if request.method == 'GET':
        try:
            customer = get_object_or_404(Customer, telegram_id=telegram_id)
            orders = Order.objects.filter(customer=customer).order_by('-created_at')
            
            orders_data = []
            for order in orders:
                orders_data.append({
                    'order_id': order.order_number,
                    'date': order.created_at.strftime("%Y-%m-%d %H:%M"),
                    'total': float(order.total_amount),
                    'status': order.status,
                    'status_display': order.get_status_display(),
                    'service_type': order.service_type,
                    'service_type_display': order.get_service_type_display(),
                })
            
            return JsonResponse({'success': True, 'orders': orders_data})
        except Exception as e:
            logger.error(f"Foydalanuvchi buyurtmalarini olishda xato: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': 'Faqat GET so\'rov qabul qilinadi'}, status=405)

@csrf_exempt
def get_order_details_api(request, order_id):
    """API: Buyurtma tafsilotlarini olish (popup uchun)"""
    if request.method == 'GET':
        try:
            order = get_object_or_404(Order, id=order_id)
            
            order_items_data = []
            for item in order.items.all():
                order_items_data.append({
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                    'price': float(item.price),
                    'total': float(item.total),
                })
                
            status_history_data = []
            for history in order.status_history.all().order_by('changed_at'):
                status_history_data.append({
                    'old_status': history.old_status,
                    'new_status': history.new_status,
                    'new_status_display': dict(Order.STATUS_CHOICES).get(history.new_status, history.new_status),
                    'timestamp': history.changed_at.strftime("%Y-%m-%d %H:%M:%S"),
                    'notes': history.notes,
                    'changed_by': history.changed_by.username if history.changed_by else 'Tizim',
                })

            order_data = {
                'id': order.id,
                'order_number': order.order_number,
                'created_at': order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                'status': order.status,
                'status_display': order.get_status_display(),
                'payment_method': order.payment_method,
                'payment_method_display': order.get_payment_method_display(),
                'service_type': order.service_type,
                'service_type_display': order.get_service_type_display(),
                'latitude': float(order.latitude) if order.latitude else None,
                'longitude': float(order.longitude) if order.longitude else None,
                'address': order.address,
                'products_total': float(order.products_total),
                'delivery_cost': float(order.delivery_cost),
                'total_amount': float(order.total_amount),
                'customer': {
                    'full_name': order.customer.full_name,
                    'phone_number': order.customer.phone_number,
                },
                'items': order_items_data,
                'status_history': status_history_data,
            }
            
            return JsonResponse({'success': True, 'order': order_data})
        except Exception as e:
            logger.error(f"Buyurtma tafsilotlarini olishda xato: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': 'Faqat GET so\'rov qabul qilinadi'}, status=405)

@csrf_exempt
def toggle_product_availability(request, product_id):
    """API: Mahsulot mavjudligini almashtirish"""
    if request.method == 'POST':
        try:
            product = get_object_or_404(Product, id=product_id)
            product.is_available = not product.is_available
            product.save()
            
            return JsonResponse({
                'success': True,
                'is_available': product.is_available,
                'message': f'Mahsulot "{product.name}" holati muvaffaqiyatli yangilandi.'
            })
        except Product.DoesNotExist:
            logger.error(f"Mahsulot topilmadi: ID {product_id}")
            return JsonResponse({'success': False, 'message': 'Mahsulot topilmadi.'}, status=404)
        except Exception as e:
            logger.error(f"Mahsulot mavjudligini yangilashda xato: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False, 'message': 'Faqat POST so\'rov qabul qilinadi'}, status=405)
