from django.utils.translation import gettext_lazy as _t

class DocumentTemplateType:
    RULES = "rules"  # Правила обмена
    PRIVACY = "privacy"  # Политика конфиденциальности
    TOS = "tos"  # Пользовательское соглашение
    DISCLAIMER = "disclaimer"  # Риски / Отказ от ответственности
    GOV_REQUESTS = "gov_requests"  # Руководство по запросам от компетентных органов
    AML_KYC = "aml_kyc"  # Политика AML / KYC
    FAQ = "faq"  # Вопросы и ответы (FAQ)

    CHOICES = (
        (RULES, _t("Правила обмена")),
        (PRIVACY, _t("Политика конфиденциальности")),
        (TOS, _t("Пользовательское соглашение")),
        (DISCLAIMER, _t("Риски / Отказ от ответственности")),
        (GOV_REQUESTS, _t("Руководство по запросам от компетентных органов")),
        (AML_KYC, _t("Политика AML / KYC")),
        (FAQ, _t("Вопросы и ответы (FAQ)")),
    )
