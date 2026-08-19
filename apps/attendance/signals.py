from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import HomeOfficeEntry, PunchLog


@receiver(post_delete, sender=PunchLog)
def recalc_on_punch_delete(sender, instance, **kwargs):
    if instance.employee_id:
        from .services import rebuild_day
        rebuild_day(instance.employee, instance.punch_time.date())


@receiver(post_save, sender=HomeOfficeEntry)
def recalc_on_home_office(sender, instance, **kwargs):
    from .services import rebuild_day
    rebuild_day(instance.employee, instance.date)
