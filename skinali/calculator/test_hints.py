from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict
from django.test import TestCase
from django.urls import reverse

from . import tests as admin_tests
from .models import CalculatorService, CalculatorSettings, CalculatorTariffs, TARIFF_HINT_FIELDS
from .test_calculation import CalculationFixture


class CalculatorHintTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('hint-owner', password=None)

    def setUp(self):
        CalculatorSettings.objects.update(is_enabled=True)
        self.tariffs_url = reverse('admin:calculator_calculatortariffs_change', args=[self.settings.pk])

    def clear_hints(self, value=''):
        CalculatorTariffs.objects.update(**dict.fromkeys(TARIFF_HINT_FIELDS, value))
        CalculatorService.objects.update(hint=value)

    def test_migration_preserves_previous_hints_and_new_service_has_no_default_hint(self):
        self.settings.refresh_from_db()
        self.assertTrue(all(getattr(self.settings, name) for name in TARIFF_HINT_FIELDS))
        self.assertIn('6000 мм', self.settings.panels_hint)
        self.assertTrue(all(CalculatorService.objects.values_list('hint', flat=True)))
        self.assertEqual(self.settings.services.get(code='measurement').hint,
                         'Эта услуга включена в стоимость. Доплата не начисляется.')
        service = CalculatorService.objects.create(settings=self.settings, name='Новая услуга')
        self.assertEqual(service.hint, '')

    def test_blank_and_whitespace_hints_hide_every_question_mark(self):
        for value in ('', ' \t\n '):
            with self.subTest(value=value):
                self.clear_hints(value)
                response = self.client.get(reverse('price'))
                self.assertNotContains(response, '<details class="price-hint"')
                self.assertEqual(response.context['calculator_config']['panels_hint'], '')
                self.assertTrue(all(not item['hint'] for item in response.context['calculator_config']['services']))

    def test_saved_hints_render_for_each_parameter_without_built_in_fallback(self):
        self.clear_hints()
        for field in TARIFF_HINT_FIELDS:
            with self.subTest(field=field):
                CalculatorTariffs.objects.update(**{field: f'  Описание {field}  '})
                response = self.client.get(reverse('price'))
                self.assertContains(response, f'Описание {field}')
                self.assertContains(response, '<details class="price-hint"', count=1)
                CalculatorTariffs.objects.update(**{field: ''})
        for code in ('backlight', 'measurement'):
            with self.subTest(service=code):
                self.settings.services.filter(code=code).update(hint=f'Описание услуги {code}')
                response = self.client.get(reverse('price'))
                self.assertContains(response, f'Описание услуги {code}')
                self.assertContains(response, '<details class="price-hint"', count=1)
                self.settings.services.filter(code=code).update(hint='')

    def test_hints_are_plain_text_preserve_line_breaks_and_are_safe_in_json(self):
        self.clear_hints()
        text = '<script>alert(1)</script>\nВторая строка'
        CalculatorTariffs.objects.update(glass_type_hint=text)
        self.settings.services.filter(code='measurement').update(hint=text)
        response = self.client.get(reverse('price'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;<br>Вторая строка')
        self.assertContains(response, '\\u003Cscript\\u003E')

    def test_tariffs_edit_fixed_hints_without_exposing_or_changing_service_hints(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.tariffs_url)
        fields = response.context['adminform'].form.fields
        for field in TARIFF_HINT_FIELDS:
            self.assertIn(field, fields)
            self.assertEqual(fields[field].widget.attrs['rows'], 3)
        self.assertNotContains(response, 'name="services-0-hint"')
        for form in response.context['inline_admin_formsets'][0].formset.forms:
            self.assertNotIn('hint', form.fields)
        service_hints = dict(self.settings.services.values_list('pk', 'hint'))
        data = admin_tests.CalculatorAdminTests.settings_data(
            self, **{field: f'  Новая подсказка {field}  ' for field in TARIFF_HINT_FIELDS},
        )
        data['services-0-hint'] = 'Подменённая подсказка'
        self.assertEqual(self.client.post(self.tariffs_url, data).status_code, 302)
        self.settings.refresh_from_db()
        for field in TARIFF_HINT_FIELDS:
            self.assertEqual(getattr(self.settings, field), f'Новая подсказка {field}')
        self.assertEqual(dict(self.settings.services.values_list('pk', 'hint')), service_hints)
        self.assertTrue(LogEntry.objects.filter(
            user=self.owner, content_type__model='calculatortariffs', action_flag=CHANGE,
        ).exists())
        response = self.client.get(reverse('price'))
        self.assertContains(response, 'Новая подсказка glass_type_hint')
        self.assertNotContains(response, 'Подменённая подсказка')
        data = admin_tests.CalculatorAdminTests.settings_data(
            self, **dict.fromkeys(TARIFF_HINT_FIELDS, ''),
        )
        self.assertEqual(self.client.post(self.tariffs_url, data).status_code, 302)
        response = self.client.get(reverse('price'))
        self.assertEqual(response.context['calculator_config']['glass_type']['hint'], '')
        self.assertEqual(dict(self.settings.services.values_list('pk', 'hint')), service_hints)

    def test_service_editor_saves_and_clears_hint_for_included_service(self):
        self.client.force_login(self.owner)
        service = self.settings.services.get(code='measurement')
        url = reverse('admin:calculator_calculatorservice_change', args=[service.pk])
        self.assertIn('hint', self.client.get(url).context['adminform'].form.fields)
        self.assertIn('hint', self.client.get(reverse('admin:calculator_calculatorservice_add')).context['adminform'].form.fields)
        for hint in ('Подсказка из редактора услуги', ''):
            with self.subTest(hint=hint):
                values = {**model_to_dict(service), 'hint': hint}
                data = {name: 'on' if value is True else '' if value is False or value is None else str(value)
                        for name, value in values.items() if name not in ('id', 'settings', 'code', 'position')}
                self.assertEqual(self.client.post(url, data).status_code, 302)
                service.refresh_from_db()
                self.assertEqual(service.hint, hint)
        self.assertTrue(LogEntry.objects.filter(
            user=self.owner, content_type__model='calculatorservice', object_id=str(service.pk), action_flag=CHANGE,
        ).exists())

    def test_model_and_admin_form_reject_hints_longer_than_2000_characters(self):
        service = self.settings.services.get(code='measurement')
        for instance, field in ((self.settings, name) for name in TARIFF_HINT_FIELDS):
            with self.subTest(field=field):
                setattr(instance, field, 'x' * 2001)
                with self.assertRaises(ValidationError):
                    instance.save()
                instance.refresh_from_db()
        service.hint = 'x' * 2001
        with self.assertRaises(ValidationError):
            service.save()
        self.client.force_login(self.owner)
        response = self.client.post(self.tariffs_url, admin_tests.CalculatorAdminTests.settings_data(
            self, glass_type_hint='x' * 2001,
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIn('glass_type_hint', response.context['adminform'].form.errors)
