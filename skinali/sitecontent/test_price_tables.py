import json
from datetime import timedelta

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from calculator.models import CalculatorSettings
from .models import PriceTable, PriceTableRow, SitePage


class PriceTableModelTests(TestCase):
    def test_text_prices_validation_defaults_and_cascade(self):
        table = PriceTable.objects.create(title='  Дизайнерские услуги  ')
        self.assertFalse(table.is_published)
        self.assertEqual(table.title, 'Дизайнерские услуги')
        self.assertEqual((table.service_column, table.price_column), ('Услуга', 'Стоимость'))
        for price in ('Бесплатно', 'от 25 руб.', '3 руб. за каждый макет', 'По согласованию'):
            row = PriceTableRow.objects.create(table=table, description='  Макет  ', price=price)
            self.assertEqual(row.description, 'Макет')
        for model, values in (
            (PriceTable, {'title': '   '}),
            (PriceTable, {'title': 'Таблица', 'service_column': ' '}),
            (PriceTableRow, {'table': table, 'description': ' ', 'price': 'Бесплатно'}),
            (PriceTableRow, {'table': table, 'description': 'Макет', 'price': ' '}),
            (PriceTableRow, {'table': table, 'description': 'Макет', 'price': 'x' * 501}),
            (PriceTable, {'title': 'Таблица', 'position': -1}),
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                model.objects.create(**values)
        table.delete()
        self.assertFalse(PriceTableRow.objects.exists())

    def test_table_and_row_changes_touch_only_price_page(self):
        old = timezone.now() - timedelta(days=2)
        operations = []
        table = PriceTable.objects.create(title='Таблица')
        row = PriceTableRow.objects.create(table=table, description='Услуга', price='Бесплатно')
        operations.extend((table.save, row.save, row.delete, table.delete))
        for operation in operations:
            SitePage.objects.update(updated_at=old)
            operation()
            self.assertGreater(SitePage.objects.get(pk=SitePage.Code.PRICE).updated_at, old)
            self.assertFalse(SitePage.objects.exclude(pk=SitePage.Code.PRICE).exclude(updated_at=old).exists())


class PriceTableRenderingTests(TestCase):
    def setUp(self):
        self.table = PriceTable.objects.create(title='Дизайнерские услуги', is_published=True)
        self.row = PriceTableRow.objects.create(table=self.table, description='Макет', price='Бесплатно')

    def test_published_tables_follow_calculator_and_stay_visible_when_disabled(self):
        CalculatorSettings.objects.filter(pk=CalculatorSettings.CODE).update(is_enabled=False)
        self.table.service_column = 'Дизайнерская работа'
        self.table.price_column = 'Цена услуги'
        self.table.note = 'Первая строка\nВторая строка'
        self.table.save()
        hidden = PriceTable.objects.create(title='Скрытая таблица')
        PriceTableRow.objects.create(table=hidden, description='Не показывать', price='10 руб.')
        PriceTable.objects.create(title='Пустая опубликованная таблица', is_published=True)
        response = self.client.get(reverse('price'))
        self.assertContains(response, self.table.title)
        self.assertContains(response, 'Дизайнерская работа')
        self.assertContains(response, 'Цена услуги')
        self.assertContains(response, '<th scope="row">Макет</th>', html=True)
        self.assertContains(response, 'Первая строка<br>Вторая строка', html=True)
        self.assertNotContains(response, 'Скрытая таблица')
        self.assertNotContains(response, 'Пустая опубликованная таблица')
        self.assertNotContains(response, 'price-calculator-config')
        self.assertLess(response.content.decode().index('Узнать стоимость'), response.content.decode().index('class="price-tables"'))
        self.assertEqual(self.client.head(reverse('price')).status_code, 200)

    def test_tables_are_exclusive_to_price_page_and_removed_when_unpublished(self):
        self.assertNotContains(self.client.get(reverse('home')), self.table.title)
        self.table.is_published = False
        self.table.save()
        response = self.client.get(reverse('price'))
        self.assertNotContains(response, self.table.title)
        self.assertNotContains(response, 'class="price-tables"')

    def test_every_editable_text_is_escaped_and_newlines_are_preserved(self):
        payload = '<img src=x onerror=alert(1)>'
        for field in ('title', 'service_column', 'price_column', 'note'):
            setattr(self.table, field, payload)
        self.table.save()
        self.row.description = f'{payload}\nДругая строка'
        self.row.price = payload
        self.row.save()
        response = self.client.get(reverse('price'))
        self.assertNotContains(response, payload)
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;', count=6)
        self.assertContains(response, '&gt;<br>Другая строка')

    def test_public_order_uses_position_then_pk_and_prefetches_all_rows(self):
        PriceTableRow.objects.create(table=self.table, description='Первая услуга', price='10', position=0)
        self.row.position = 20
        self.row.save()
        earlier = PriceTable.objects.create(title='Первая таблица', position=0, is_published=True)
        PriceTableRow.objects.create(table=earlier, description='Её услуга', price='20')
        response = self.client.get(reverse('price'))
        self.assertEqual([table.pk for table in response.context['price_tables']], [self.table.pk, earlier.pk])
        content = response.content.decode()
        self.assertLess(content.index('Первая услуга'), content.index('<th scope="row">Макет'))
        with CaptureQueriesContext(connection) as queries:
            render_to_string('sitecontent/includes/price_tables.html', {
                'tables': PriceTable.objects.filter(is_published=True).prefetch_related('rows'),
            })
        self.assertEqual(len(queries), 2)


class PriceTableAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('price-table-admin', password='test-password')
        cls.staff = get_user_model().objects.create_user('price-table-staff', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__app_label='sitecontent'))

    def setUp(self):
        self.client.force_login(self.user)
        self.table = PriceTable.objects.create(title='Услуги', position=1)
        self.row = PriceTableRow.objects.create(table=self.table, description='Макет', price='Бесплатно', position=1)
        self.change_url = reverse('admin:sitecontent_pricetable_change', args=[self.table.pk])
        self.reorder_url = reverse('admin:sitecontent_pricetable_reorder')

    def payload(self, **overrides):
        data = {
            'title': 'Услуги', 'service_column': 'Услуга', 'price_column': 'Стоимость', 'note': '',
            'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '1',
            'rows-MIN_NUM_FORMS': '0', 'rows-MAX_NUM_FORMS': '1000',
            'rows-0-id': self.row.pk, 'rows-0-table': self.table.pk,
            'rows-0-description': 'Макет', 'rows-0-price': 'Бесплатно', 'rows-0-position': '1',
            '_save': 'Сохранить',
        }
        return data | overrides

    def test_admin_exposes_one_section_with_inline_rows_and_shared_order_controls(self):
        listing = self.client.get(reverse('admin:sitecontent_pricetable_changelist'))
        self.assertContains(listing, 'Таблицы страницы «Цена»')
        self.assertContains(listing, 'data-price-table-id')
        editor = self.client.get(self.change_url)
        self.assertContains(editor, 'sitecontent/js/admin-price-tables.js')
        self.assertContains(editor, 'skinali/js/admin-order.js')
        self.assertContains(editor, 'data-price-row-order')
        self.assertContains(editor, 'name="rows-0-position"')
        self.assertNotContains(editor, 'quill-editor.js')

    def test_create_table_with_rows_appends_it_and_logs_addition(self):
        data = self.payload(**{
            'title': 'Новая таблица', 'rows-INITIAL_FORMS': '0',
            'rows-0-id': '', 'rows-0-table': '', 'is_published': 'on',
        })
        response = self.client.post(reverse('admin:sitecontent_pricetable_add'), data)
        self.assertEqual(response.status_code, 302)
        table = PriceTable.objects.get(title='Новая таблица')
        self.assertEqual(table.position, 2)
        self.assertTrue(table.is_published)
        self.assertEqual(table.rows.get().price, 'Бесплатно')
        self.assertTrue(LogEntry.objects.filter(object_id=str(table.pk), action_flag=ADDITION).exists())

    def test_inline_can_edit_add_reorder_and_delete_rows_atomically(self):
        removed = PriceTableRow.objects.create(table=self.table, description='Удалить', price='10', position=2)
        response = self.client.post(self.change_url, self.payload(**{
            'is_published': 'on', 'rows-TOTAL_FORMS': '4', 'rows-INITIAL_FORMS': '2',
            'rows-0-description': 'Изменённая услуга', 'rows-0-position': '2',
            'rows-1-id': removed.pk, 'rows-1-table': self.table.pk,
            'rows-1-description': removed.description, 'rows-1-price': removed.price,
            'rows-1-position': '3', 'rows-1-DELETE': 'on',
            'rows-2-id': '', 'rows-2-table': self.table.pk, 'rows-2-description': 'Новая услуга',
            'rows-2-price': 'По согласованию', 'rows-2-position': '1',
            'rows-3-id': '', 'rows-3-table': self.table.pk, 'rows-3-description': '',
            'rows-3-price': '', 'rows-3-position': '4',
        }))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.table.rows.values_list('description', flat=True)), ['Новая услуга', 'Изменённая услуга'])
        self.assertFalse(PriceTableRow.objects.filter(pk=removed.pk).exists())
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.table.pk), action_flag=CHANGE).exists())

    def test_invalid_row_does_not_save_parent_or_other_rows(self):
        response = self.client.post(self.change_url, self.payload(**{'title': 'Не сохранять', 'rows-0-price': ''}))
        self.assertEqual(response.status_code, 200)
        self.table.refresh_from_db()
        self.row.refresh_from_db()
        self.assertEqual(self.table.title, 'Услуги')
        self.assertEqual(self.row.price, 'Бесплатно')

    def test_published_table_requires_a_row_but_empty_draft_is_allowed(self):
        data = self.payload(**{'rows-0-DELETE': 'on', 'is_published': 'on'})
        response = self.client.post(self.change_url, data)
        self.assertContains(response, 'Добавьте хотя бы одну строку перед публикацией таблицы.')
        self.assertTrue(self.table.rows.exists())
        data.pop('is_published')
        self.assertEqual(self.client.post(self.change_url, data).status_code, 302)
        self.assertFalse(self.table.rows.exists())

    def test_reorder_preserves_unsubmitted_slots_and_updates_lastmod_and_log(self):
        middle = PriceTable.objects.create(title='Средняя', position=2)
        last = PriceTable.objects.create(title='Последняя', position=3)
        old = timezone.now() - timedelta(days=2)
        SitePage.objects.filter(pk=SitePage.Code.PRICE).update(updated_at=old)
        response = self.client.post(self.reorder_url, json.dumps({
            'ordered_ids': [last.pk, self.table.pk],
        }), content_type='application/json')
        self.assertEqual(response.json(), {'saved': True})
        self.assertEqual(list(PriceTable.objects.values_list('pk', flat=True)), [last.pk, middle.pk, self.table.pk])
        self.assertGreater(SitePage.objects.get(pk=SitePage.Code.PRICE).updated_at, old)
        self.assertTrue(LogEntry.objects.filter(object_id=str(last.pk), action_flag=CHANGE).exists())

    def test_reorder_rejects_invalid_or_stale_payloads_without_modifications(self):
        for payload, status in (
            ({'ordered_ids': [self.table.pk, self.table.pk]}, 400),
            ({'ordered_ids': [True]}, 400), ({'ordered_ids': []}, 400),
            ({'ordered_ids': ['1']}, 400), ({'ordered_ids': [-1]}, 400),
            ({'ordered_ids': [999999]}, 409), ([], 400), ({}, 400),
        ):
            with self.subTest(payload=payload):
                response = self.client.post(self.reorder_url, json.dumps(payload), content_type='application/json')
                self.assertEqual(response.status_code, status)
        self.assertEqual(self.client.post(self.reorder_url, '{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get(self.reorder_url).status_code, 405)
        self.table.refresh_from_db()
        self.assertEqual(self.table.position, 1)

    def test_staff_is_denied_even_with_model_permissions_and_posts_require_csrf(self):
        self.client.force_login(self.staff)
        for url in (reverse('admin:sitecontent_pricetable_changelist'),
                    reverse('admin:sitecontent_pricetable_add'), self.change_url):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(self.reorder_url, json.dumps({
            'ordered_ids': [self.table.pk],
        }), content_type='application/json').status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.change_url, self.payload()).status_code, 403)
        self.assertEqual(csrf_client.post(self.reorder_url, json.dumps({
            'ordered_ids': [self.table.pk],
        }), content_type='application/json').status_code, 403)

    def test_table_delete_uses_standard_confirmation_and_removes_its_rows(self):
        url = reverse('admin:sitecontent_pricetable_delete', args=[self.table.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'post': 'yes'}).status_code, 302)
        self.assertFalse(PriceTable.objects.filter(pk=self.table.pk).exists())
        self.assertFalse(PriceTableRow.objects.filter(pk=self.row.pk).exists())
