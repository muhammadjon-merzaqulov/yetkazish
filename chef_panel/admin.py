from django.contrib import admin
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import ValidationError
from django import forms
from .models import Category, Product, Customer, Order, OrderItem, OrderStatusHistory, BotSettings
from .utils import send_telegram_message
import logging

logger = logging.getLogger(__name__)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'is_available', 'created_at']
    list_filter = ['category', 'is_available', 'created_at']
    search_fields = ['name', 'description']
    list_editable = ['price', 'is_available']

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone_number', 'telegram_id', 'created_at']
    search_fields = ['full_name', 'phone_number']
    readonly_fields = ['telegram_id', 'created_at']

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['total']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'customer', 'status', 'total_amount', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['order_number', 'customer__full_name', 'customer__phone_number']
    readonly_fields = ['order_number', 'created_at', 'confirmed_at', 'ready_at', 'delivered_at']
    inlines = [OrderItemInline]
    
    fieldsets = (
        ('Asosiy ma\'lumotlar', {
            'fields': ('order_number', 'customer', 'telegram_user_id', 'status', 'payment_method')
        }),
        ('Manzil', {
            'fields': ('latitude', 'longitude', 'address')
        }),
        ('Narxlar', {
            'fields': ('products_total', 'delivery_cost', 'total_amount')
        }),
        ('Vaqt ma\'lumotlari', {
            'fields': ('created_at', 'confirmed_at', 'ready_at', 'delivered_at')
        }),
        ('Telegram Xabar IDlari', {
            'fields': ('chef_message_id', 'user_message_id', 'courier_message_id'),
            'classes': ('collapse',)
        }),
    )

@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ['order', 'old_status', 'new_status', 'changed_by', 'changed_at']
    list_filter = ['old_status', 'new_status', 'changed_at']
    readonly_fields = ['changed_at']

class BotSettingsForm(forms.ModelForm):
    class Meta:
        model = BotSettings
        fields = '__all__'
        widgets = {
            'service_start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'service_end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'delivery_base_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '1000', 'min': '0'}),
            'delivery_cost_per_extra_km_block': forms.NumberInput(attrs={'class': 'form-control', 'step': '1000', 'min': '0'}),
            'delivery_max_radius_km': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '1', 'max': '50'}),
            'broadcast_message_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'E\'lon matnini kiriting...'}),
        }
        labels = {
            'service_start_time': 'Xizmat boshlanish vaqti',
            'service_end_time': 'Xizmat tugash vaqti',
            'delivery_base_cost': 'Yetkazib berish boshlang\'ich narxi (so\'m)',
            'delivery_cost_per_extra_km_block': 'Har km uchun qo\'shimcha narx (so\'m)',
            'delivery_max_radius_km': 'Maksimal yetkazib berish radiusi (km)',
            'broadcast_message_text': 'E\'lon matni',
        }
        help_texts = {
            'service_start_time': 'Bot qaysi vaqtdan buyurtma qabul qilishni boshlaydi',
            'service_end_time': 'Bot qaysi vaqtgacha buyurtma qabul qiladi',
            'delivery_base_cost': 'Har qanday masofada minimal yetkazib berish narxi',
            'delivery_cost_per_extra_km_block': 'Birinchi kilometrdan keyin har km uchun qo\'shimcha to\'lov',
            'delivery_max_radius_km': 'Bu masofadan uzoqroqqa yetkazib berish yo\'q',
            'broadcast_message_text': 'Barcha foydalanuvchilarga yuborilishi mumkin bo\'lgan e\'lon matni',
        }

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('service_start_time')
        end_time = cleaned_data.get('service_end_time')
        base_cost = cleaned_data.get('delivery_base_cost')
        extra_cost = cleaned_data.get('delivery_cost_per_extra_km_block')
        max_radius = cleaned_data.get('delivery_max_radius_km')

        # Validate time range
        if start_time and end_time:
            if start_time == end_time:
                raise ValidationError('Boshlanish va tugash vaqti bir xil bo\'lishi mumkin emas!')

        # Validate costs
        if base_cost is not None and base_cost < 0:
            raise ValidationError('Boshlang\'ich narx manfiy bo\'lishi mumkin emas!')
        
        if extra_cost is not None and extra_cost < 0:
            raise ValidationError('Qo\'shimcha narx manfiy bo\'lishi mumkin emas!')

        # Validate radius
        if max_radius is not None:
            if max_radius < 1:
                raise ValidationError('Maksimal radius kamida 1 km bo\'lishi kerak!')
            if max_radius > 100:
                raise ValidationError('Maksimal radius 100 km dan oshmasligi kerak!')

        return cleaned_data

@admin.register(BotSettings)
class BotSettingsAdmin(admin.ModelAdmin):
    form = BotSettingsForm
    list_display = ('__str__', 'service_start_time', 'service_end_time', 'delivery_base_cost', 'delivery_max_radius_km', 'last_broadcast_sent_at')
    
    fieldsets = (
        ('Ish vaqti sozlamalari', {
            'fields': ('service_start_time', 'service_end_time'),
            'description': 'Bot qaysi vaqt oralig\'ida buyurtma qabul qiladi'
        }),
        ('Yetkazib berish sozlamalari', {
            'fields': ('delivery_base_cost', 'delivery_cost_per_extra_km_block', 'delivery_max_radius_km'),
            'description': 'Yetkazib berish narxi va masofa sozlamalari'
        }),
        ('E\'lon sozlamalari', {
            'fields': ('broadcast_message_text', 'last_broadcast_sent_at'),
            'description': 'Barcha foydalanuvchilarga e\'lon yuborish'
        }),
    )
    
    readonly_fields = ['last_broadcast_sent_at']
    
    def has_add_permission(self, request):
        # Allow adding only if no instance exists
        return not BotSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion
        return False

    def get_queryset(self, request):
        # Always show the single instance or create it if it doesn't exist
        qs = super().get_queryset(request)
        if not qs.exists():
            # Create default settings if none exist
            BotSettings.objects.create()
        return qs

    actions = ['send_broadcast', 'test_bot_connection']

    def send_broadcast(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Iltimos, faqat bitta Bot Sozlamalari obyektini tanlang.", level=messages.ERROR)
            return

        settings_obj = queryset.first()
        message_text = settings_obj.broadcast_message_text

        if not message_text:
            self.message_user(request, "E'lon matni bo'sh. Iltimos, matnni kiriting.", level=messages.ERROR)
            return

        customers = Customer.objects.all()
        sent_count = 0
        failed_count = 0

        for customer in customers:
            try:
                response = send_telegram_message(chat_id=customer.telegram_id, text=message_text)
                if response and response.get('ok'):
                    sent_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"E'lon yuborishda xato: {customer.telegram_id} - {response.get('description', 'Noma\'lum xato')}")
            except Exception as e:
                failed_count += 1
                logger.error(f"E'lon yuborishda kutilmagan xato: {customer.telegram_id} - {e}", exc_info=True)

        settings_obj.last_broadcast_sent_at = timezone.now()
        settings_obj.save()

        if failed_count == 0:
            self.message_user(request, f"✅ E'lon {sent_count} ta mijozga muvaffaqiyatli yuborildi!", level=messages.SUCCESS)
        else:
            self.message_user(request, f"⚠️ E'lon {sent_count} ta mijozga yuborildi. {failed_count} ta xato yuz berdi.", level=messages.WARNING)
    
    send_broadcast.short_description = "📢 Barcha mijozlarga e'lon yuborish"

    def test_bot_connection(self, request, queryset):
        """Test bot connection by sending a message to admin"""
        from django.conf import settings as django_settings
        
        try:
            test_message = "🤖 Bot ulanishi muvaffaqiyatli! Admin panel orqali sozlamalar ishlayapti."
            response = send_telegram_message(
                chat_id=django_settings.ADMIN_CHAT_ID, 
                text=test_message
            )
            
            if response and response.get('ok'):
                self.message_user(request, "✅ Bot ulanishi muvaffaqiyatli! Admin chatga test xabar yuborildi.", level=messages.SUCCESS)
            else:
                error_desc = response.get('description', 'Noma\'lum xato') if response else 'Javob olinmadi'
                self.message_user(request, f"❌ Bot ulanishida xato: {error_desc}", level=messages.ERROR)
        except Exception as e:
            self.message_user(request, f"❌ Bot ulanishini tekshirishda xato: {str(e)}", level=messages.ERROR)
    
    test_bot_connection.short_description = "🔧 Bot ulanishini tekshirish"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        # Show success message with current settings
        if change:
            self.message_user(
                request, 
                f"✅ Bot sozlamalari yangilandi!\n"
                f"🕐 Ish vaqti: {obj.service_start_time.strftime('%H:%M')} - {obj.service_end_time.strftime('%H:%M')}\n"
                f"💰 Boshlang'ich narx: {obj.delivery_base_cost:,} so'm\n"
                f"📏 Maksimal radius: {obj.delivery_max_radius_km} km\n"
                f"⚠️ Eslatma: Bot avtomatik ravishda yangi sozlamalarni qo'llaydi.",
                level=messages.SUCCESS
            )
        else:
            self.message_user(request, "✅ Bot sozlamalari yaratildi!", level=messages.SUCCESS)

    def changelist_view(self, request, extra_context=None):
        # Add custom context for the changelist
        extra_context = extra_context or {}
        
        # Get current settings
        try:
            settings_obj = BotSettings.objects.first()
            if settings_obj:
                extra_context['current_settings'] = {
                    'service_hours': f"{settings_obj.service_start_time.strftime('%H:%M')} - {settings_obj.service_end_time.strftime('%H:%M')}",
                    'base_cost': f"{settings_obj.delivery_base_cost:,} so'm",
                    'extra_cost': f"{settings_obj.delivery_cost_per_extra_km_block:,} so'm/km",
                    'max_radius': f"{settings_obj.delivery_max_radius_km} km",
                    'last_broadcast': settings_obj.last_broadcast_sent_at.strftime('%Y-%m-%d %H:%M') if settings_obj.last_broadcast_sent_at else 'Hech qachon',
                }
        except Exception as e:
            logger.error(f"Error getting current settings: {e}")
        
        return super().changelist_view(request, extra_context=extra_context)
