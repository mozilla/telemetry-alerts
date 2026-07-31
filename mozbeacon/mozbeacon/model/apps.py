from django.apps import AppConfig


class ModelConfig(AppConfig):
    name = "mozbeacon.model"
    label = "model"
    default_auto_field = "django.db.models.BigAutoField"
