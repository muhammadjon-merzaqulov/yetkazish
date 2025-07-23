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
  }
  
  # Oxirgi buyurtmalar
  recent_orders = Order.objects.filter(
      status__in=['yangi', 'tasdiqlangan']
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

  context = {
      'stats': stats,
      'recent_orders': recent_orders,
      'top_customers': top_customers,
      'weekly_stats': weekly_stats,
      'today_sales': today_sales, # Yangi bugungi savdo
      'sales_by_status': sales_by_status_display, # Yangi holatlar bo'yicha savdo
  }
  return render(request, 'chef_panel/dashboard.html', context)

def order_list(request):
  """Barcha buyurtmalar ro'yxati"""
  status_filter = request.GET.get('status', '')
  search = request.GET.get('search', '')
  
  orders = Order.objects.all().order_by('-created_at')
  
  if status_filter:
      orders = orders.filter(status=status_filter)
  
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
      'search': search,
      'status_choices': Order.STATUS_CHOICES,
  }
  return render(request, 'chef_panel/order_list.html', context)

def new_orders(request):
  """Yangi buyurtmalar"""
  orders = Order.objects.filter(
      status__in=['yangi', 'tasdiqlangan']
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
              latitude=data.get('location', {}).get('latitude'),
              longitude=data.get('location', {}).get('longitude'),
              address=data.get('address', ''),
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
          if order.address:
              chef_text += f"🏠 Manzil: {order.address}\n"
          else:
              chef_text += "📍 Manzil: Faqat lokatsiya\n"
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
          
          if order.latitude and order.longitude:
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
          if order.address:
              user_text += f"🏠 Manzil: {order.address}\n"
          else:
              user_text += "📍 Manzil: Faqat lokatsiya\n"
          if order.latitude and order.longitude:
              user_text += f"📍 Lokatsiya: https://www.google.com/maps?q={order.latitude},{order.longitude}\n"
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
      "bekor_qilingan": "❌"
  }
  emoji = status_emoji.get(new_status, "📋")

  # Foydalanuvchi xabarini yangilash
  user_text = f"✅ **Buyurtmangiz qabul qilindi!**\n\n"
  user_text += f"📋 Buyurtma ID: **{order.order_number}**\n"
  user_text += f"👨‍💼 Ism: {order.customer.full_name}\n"
  user_text += f"📱 Telefon: {order.customer.phone_number}\n"
  user_text += f"💳 To'lov usuli: {order.get_payment_method_display()}\n"
  if order.address:
      user_text += f"🏠 Manzil: {order.address}\n"
  else:
      user_text += "📍 Manzil: Faqat lokatsiya\n"
  if order.latitude and order.longitude:
      user_text += f"📍 Lokatsiya: https://www.google.com/maps?q={order.latitude},{order.longitude}\n"
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
      if order.address:
          chef_text += f"🏠 Manzil: {order.address}\n"
      else:
          chef_text += "📍 Manzil: Faqat lokatsiya\n"
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
      # If status is 'tayor', 'yolda', 'yetkazildi', 'bekor_qilingan', no more actions for chef
      
      send_telegram_message(
          chat_id=settings.CHEF_CHAT_ID,
          text=chef_text,
          reply_markup={'inline_keyboard': chef_keyboard},
          message_id=order.chef_message_id
      )

  # Kuryer xabarini yangilash (agar mavjud bo'lsa)
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
def cancel_order(request, order_id):
  """Buyurtmani bekor qilish"""
  if request.method == 'POST':
      order = get_object_or_404(Order, id=order_id)
      
      if order.status not in ['yetkazildi', 'bekor_qilingan']:
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
  """Mahsulot qo'shish"""
  if request.method == 'POST':
      form = ProductForm(request.POST, request.FILES)
      if form.is_valid():
          form.save()
          messages.success(request, 'Mahsulot muvaffaqiyatli qo\'shildi!')
          return redirect('chef_panel:product_list')
  else:
      form = ProductForm()
  
  context = {'form': form}
  return render(request, 'chef_panel/add_product.html', context)

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
  
  context = {'form': form, 'product': product}
  return render(request, 'chef_panel/edit_product.html', context)

def category_list(request):
  """Kategoriyalar ro'yxati"""
  categories = Category.objects.all().order_by('name')
  context = {'categories': categories}
  return render(request, 'chef_panel/category_list.html', context)

def add_category(request):
  """Kategoriya qo'shish"""
  if request.method == 'POST':
      form = CategoryForm(request.POST)
      if form.is_valid():
          form.save()
          messages.success(request, 'Kategoriya muvaffaqiyatli qo\'shildi!')
          return redirect('chef_panel:category_list')
  else:
      form = CategoryForm()
  
  context = {'form': form}
  return render(request, 'chef_panel/add_category.html', context)

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
          
          # Faqat ruxsat etilgan status o'zgarishlarini tekshirish
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
          for history in order.status_history.all().order_by('changed_at'): # Changed 'timestamp' to 'changed_at'
              status_history_data.append({
                  'old_status': history.old_status,
                  'new_status': history.new_status,
                  'new_status_display': dict(Order.STATUS_CHOICES).get(history.new_status, history.new_status),
                  'timestamp': history.changed_at.strftime("%Y-%m-%d %H:%M:%S"), # Changed 'history.timestamp' to 'history.changed_at'
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



# # ----------------------------------------------------
# # Fikr bildirish
# # ----------------------------------------------------
# async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#     context.user_data["awaiting_feedback"] = True
#     await query.message.reply_text(
#         "✍️ Fikringizni yozing. Bekor qilish uchun /cancel ni yozing."
#     )

# async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     text = update.message.text
#     if context.user_data.get('awaiting_address'):
#         await handle_address(update, context)
#         return

#     if context.user_data.get("awaiting_feedback"):
#         context.user_data["awaiting_feedback"] = False
#         user = update.effective_user
#         phone = context.user_data.get('phone_number', "Noma'lum")
#         full_name = context.user_data.get('full_name', user.full_name)

#         admin_msg = (
#             f"💬 **Yangi fikr kelib tushdi!**\n\n"
#             f"👨‍💼 Muallif: {full_name}\n"
#             f"📱 Tel: {phone}\n"
#             f"🆔 User ID: {user.id}\n\n"
#             f"📝 **Fikr matni:**\n{text}"
#         )
        
#         try:
#             # Use settings.ADMIN_CHAT_ID from Django settings
#             await context.bot.send_message(chat_id=settings.ADMIN_CHAT_ID, text=admin_msg, parse_mode="Markdown")
#         except Exception as e:
#             logger.error(f"Failed to send feedback to admin: {e}")
            
#         await update.message.reply_text(
#             "✅ Fikringiz uchun rahmat! Tez orada ko'rib chiqamiz.",
#             reply_markup=main_inline_menu(context)
#         )
#         return

#     await update.message.reply_text("📨 Xabaringiz qabul qilindi.")

# # ----------------------------------------------------
# # Xatolarni boshqarish
# # ----------------------------------------------------
# async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
#     logger.error(msg="Exception while handling an update:", exc_info=context.error)
#     if isinstance(update, Update) and update.effective_user:
#         try:
#             await context.bot.send_message(
#                 chat_id=update.effective_user.id,
#                 text="❌ Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring."
#             )
#         except Exception as e:
#             logger.error(f"Failed to send error message to user: {e}")

# async def post_init(application):
#     await load_data()
#     # Store bot_settings in application.bot_data for easy access in handlers
#     application.bot_data['bot_settings'] = bot_settings # Use the global bot_settings loaded by load_data

# # ----------------------------------------------------
# # Botni ishga tushirish
# # ----------------------------------------------------
# def main():
#     application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

#     # Asosiy komandalar
#     application.add_handler(CommandHandler("start", start))

#     # Xabarlar
#     application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
#     application.add_handler(MessageHandler(filters.LOCATION, handle_location))
#     application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

#     # Oshpaz va Kuryer callbacklari (Django ORM orqali)
#     application.add_handler(CallbackQueryHandler(handle_chef_courier_status_update, pattern="^chef_confirm:"))
#     application.add_handler(CallbackQueryHandler(handle_chef_courier_status_update, pattern="^chef_ready:"))
#     application.add_handler(CallbackQueryHandler(handle_chef_courier_status_update, pattern="^chef_cancel:"))
#     application.add_handler(CallbackQueryHandler(handle_chef_courier_status_update, pattern="^courier_on_way:"))
#     application.add_handler(CallbackQueryHandler(handle_chef_courier_status_update, pattern="^courier_delivered:"))
#     application.add_handler(CallbackQueryHandler(handle_chef_courier_status_update, pattern="^courier_cancel:"))

#     # Asosiy callbacklar
#     application.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
#     application.add_handler(CallbackQueryHandler(show_menu_inline, pattern="^menu$"))
#     application.add_handler(CallbackQueryHandler(show_category, pattern="^category:"))
#     application.add_handler(CallbackQueryHandler(show_product, pattern="^product:"))
#     application.add_handler(CallbackQueryHandler(handle_quantity, pattern="^quantity:"))
#     application.add_handler(CallbackQueryHandler(add_to_cart, pattern="^add_to_cart:"))
#     application.add_handler(CallbackQueryHandler(view_cart_inline, pattern="^show_cart$"))
#     application.add_handler(CallbackQueryHandler(clear_cart, pattern="^clear_cart$"))
#     application.add_handler(CallbackQueryHandler(update_cart_handler, pattern="^update_cart:"))
#     application.add_handler(CallbackQueryHandler(checkout, pattern="^checkout$"))
#     application.add_handler(CallbackQueryHandler(final_confirm_order, pattern="^final_confirm_order$"))
#     application.add_handler(CallbackQueryHandler(cancel_order, pattern="^cancel_order$"))
#     application.add_handler(CallbackQueryHandler(feedback_callback, pattern="^feedback$"))
#     application.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
#     application.add_handler(CallbackQueryHandler(product_go_back, pattern="^product_go_back:"))

#     # Sahifalash
#     application.add_handler(CallbackQueryHandler(show_user_orders, pattern="^user_orders:"))

#     # Promo-kod
#     application.add_handler(CallbackQueryHandler(
#         lambda u, c: u.answer("🎟 Promo-kod funksiyasi hali joriy etilmagan", show_alert=True),
#         pattern="^promo_not_implemented$")
#     )

#     application.add_error_handler(error_handler)
    
#     print("🤖 Bot ishga tushmoqda...")
#     print(f"Bot Token: {settings.TELEGRAM_BOT_TOKEN[:5]}...") # Print partial token for security
#     print(f"Chef Chat ID: {settings.CHEF_CHAT_ID}")
#     print(f"Admin Chat ID: {settings.ADMIN_CHAT_ID}")
    
#     # Call load_data as an async function before starting polling
#     application.run_polling()

# if __name__ == '__main__':
#     main()
