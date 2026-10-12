import importlib
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase

from .models import Category, Pict, TagAlias, TagPict, TagSearchLemma
from .search import (
    SEARCH_LEMMA_CACHE_SIZE,
    _get_morph_analyzer,
    apply_catalog_search,
    get_search_lemmas,
    lemmatize_search_term,
    parse_search_query,
)


class SearchLemmaAnalyzerTests(SimpleTestCase):
    def setUp(self):
        lemmatize_search_term.cache_clear()
        self.addCleanup(lemmatize_search_term.cache_clear)

    def test_russian_forms_and_yo_share_one_normalized_lemma(self):
        self.assertEqual(get_search_lemmas('Ёлками, елки; ЕЛКА'), ('елка',))
        self.assertEqual(get_search_lemmas('Красными розами'), ('красный', 'роза'))

    def test_only_most_probable_parse_is_used_and_cached(self):
        analyzer = Mock()
        analyzer.parse.return_value = [
            SimpleNamespace(normal_form='стать'),
            SimpleNamespace(normal_form='сталь'),
        ]
        with patch('pict.search._get_morph_analyzer', return_value=analyzer):
            self.assertEqual(get_search_lemmas('стали'), ('стать',))
            self.assertEqual(get_search_lemmas('стали'), ('стать',))
        analyzer.parse.assert_called_once_with('стали')
        self.assertEqual(lemmatize_search_term.cache_info().maxsize, SEARCH_LEMMA_CACHE_SIZE)

    def test_numbers_latin_and_mixed_values_do_not_load_analyzer(self):
        with patch('pict.search._get_morph_analyzer') as analyzer:
            self.assertEqual(get_search_lemmas('123 BMW x5 роза123'), ('123', 'bmw', 'x5', 'роза123'))
            parse_search_query('розами')
        analyzer.assert_not_called()

    def test_first_parallel_calls_create_one_analyzer(self):
        analyzer = Mock()
        with patch('pict.search._morph_analyzer', None):
            with patch('pymorphy3.MorphAnalyzer', return_value=analyzer) as factory:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: _get_morph_analyzer(), range(16)))
        self.assertTrue(all(result is analyzer for result in results))
        factory.assert_called_once_with(lang='ru')


class SearchLemmaIndexTests(TestCase):
    @staticmethod
    def lemmas(owner):
        return set(owner.search_lemmas.values_list('lemma', flat=True))

    def test_tag_and_alias_updates_replace_obsolete_lemmas(self):
        tag = TagPict.objects.create(tag='Красные розы розами', slug='lemma-roses')
        alias = TagAlias.objects.create(tag=tag, alias='Цветок')
        self.assertEqual(self.lemmas(tag), {'красный', 'роза'})
        self.assertEqual(self.lemmas(alias), {'цветок'})

        tag.tag = 'Лилии'
        tag.save(update_fields={'tag'})
        alias.alias = 'Букеты'
        alias.save(update_fields={'alias'})
        self.assertEqual(self.lemmas(tag), {'лилия'})
        self.assertEqual(self.lemmas(alias), {'букет'})

    def test_metadata_save_does_not_index_unsaved_tag_text(self):
        tag = TagPict.objects.create(tag='Роза', slug='lemma-metadata')
        tag.tag = 'Лилии'
        tag.seo_title = 'Новый заголовок'
        tag.save(update_fields={'seo_title'})
        tag.refresh_from_db()
        self.assertEqual(tag.tag, 'Роза')
        self.assertEqual(self.lemmas(tag), {'роза'})

    def test_index_failure_rolls_back_source_update(self):
        tag = TagPict.objects.create(tag='Роза', slug='lemma-atomic')
        tag.tag = 'Лилия'
        with patch.object(TagSearchLemma, 'replace_for', side_effect=RuntimeError('index failure')):
            with self.assertRaises(RuntimeError):
                tag.save(update_fields={'tag'})
        tag.refresh_from_db()
        self.assertEqual(tag.tag, 'Роза')
        self.assertEqual(tag.normalized_tag, 'роза')
        self.assertEqual(self.lemmas(tag), {'роза'})

    def test_owners_may_share_a_lemma_and_deletions_are_cascading(self):
        first = TagPict.objects.create(tag='Роза', slug='lemma-first')
        second = TagPict.objects.create(tag='Розы', slug='lemma-second')
        alias = TagAlias.objects.create(tag=first, alias='Розами')
        self.assertEqual(TagSearchLemma.objects.filter(lemma='роза').count(), 3)
        TagAlias.objects.filter(pk=alias.pk).delete()
        self.assertEqual(TagSearchLemma.objects.filter(lemma='роза').count(), 2)
        first.delete()
        self.assertEqual(self.lemmas(second), {'роза'})
        self.assertEqual(TagSearchLemma.objects.count(), 1)

    def test_database_requires_one_owner_and_unique_owner_lemma(self):
        tag = TagPict.objects.create(tag='Роза', slug='lemma-constraints')
        alias = TagAlias.objects.create(tag=tag, alias='Цветок')
        for values in (
            {'lemma': 'безвладельца'},
            {'lemma': 'двойной', 'tag': tag, 'alias': alias},
            {'lemma': 'роза', 'tag': tag},
            {'lemma': 'цветок', 'alias': alias},
        ):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    TagSearchLemma.objects.create(**values)

    def test_rebuild_command_repairs_index_and_is_idempotent(self):
        tag = TagPict.objects.create(tag='Розы', slug='lemma-command')
        alias = TagAlias.objects.create(tag=tag, alias='Букет')
        TagSearchLemma.objects.all().delete()
        TagSearchLemma.objects.create(tag=tag, lemma='устаревший')
        output = StringIO()
        call_command('rebuild_search_lemmas', database='default', stdout=output)
        self.assertEqual(self.lemmas(tag), {'роза'})
        self.assertEqual(self.lemmas(alias), {'букет'})
        self.assertIn('тегов — 1, синонимов — 1', output.getvalue())
        first_ids = set(TagSearchLemma.objects.values_list('pk', flat=True))
        call_command('rebuild_search_lemmas', stdout=StringIO())
        self.assertEqual(set(TagSearchLemma.objects.values_list('pk', flat=True)), first_ids)

    def test_data_migration_populates_historical_tags_and_aliases(self):
        migration = importlib.import_module('pict.migrations.0038_tag_search_lemmas')
        apps = MigrationExecutor(connection).loader.project_state([
            ('pict', '0038_tag_search_lemmas'),
        ]).apps
        historical_tag = apps.get_model('pict', 'TagPict').objects.create(
            tag='Красные автомобили', normalized_tag='красные автомобили', slug='lemma-migration',
        )
        historical_alias = apps.get_model('pict', 'TagAlias').objects.create(
            tag_id=historical_tag.pk, alias='Машина', normalized_alias='машина',
        )
        self.assertFalse(TagSearchLemma.objects.exists())
        migration.populate_search_lemmas(apps, SimpleNamespace(connection=connection))
        self.assertEqual(set(TagSearchLemma.objects.filter(tag_id=historical_tag.pk).values_list('lemma', flat=True)), {'красный', 'автомобиль'})
        self.assertEqual(set(TagSearchLemma.objects.filter(alias_id=historical_alias.pk).values_list('lemma', flat=True)), {'машина'})


class LemmatizedCatalogSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(cat='Автомобили', slug='lemma-category')
        cls.other_category = Category.objects.create(cat='Другая', slug='lemma-other-category')
        cls.car_tag = TagPict.objects.create(tag='Автомобиль', slug='lemma-car')
        cls.plural_tag = TagPict.objects.create(tag='Автомобили', slug='lemma-cars')
        cls.partial_tag = TagPict.objects.create(tag='Автомобильный интерьер', slug='lemma-interior')
        cls.red_tag = TagPict.objects.create(tag='Красный', slug='lemma-red')
        cls.alias = TagAlias.objects.create(tag=cls.car_tag, alias='Машина')
        cls.car = cls.picture(5001, cls.car_tag, cls.red_tag)
        cls.plural_car = cls.picture(5002, cls.plural_tag)
        cls.partial_car = cls.picture(5003, cls.partial_tag)
        cls.hidden_car = cls.picture(5004, cls.car_tag, is_published=False)

    @classmethod
    def picture(cls, number, *tags, is_published=True):
        picture = Pict.objects.create(name=number, alt=f'Изображение {number}', photo=f'photos/{number}.jpg', is_published=is_published)
        picture.tags.add(*tags)
        picture.cat.add(cls.category)
        return picture

    def search(self, query, queryset=None):
        if queryset is None:
            queryset = Pict.objects.published()
        return list(apply_catalog_search(queryset, parse_search_query(query)))

    def test_tag_forms_match_and_exact_tag_precedes_newer_lemma_match(self):
        self.assertEqual(self.search('автомобиль'), [self.car, self.plural_car])
        self.assertEqual(self.search('автомобилями'), [self.plural_car, self.car])
        self.assertEqual(self.search('автомобили'), [self.plural_car, self.car])

    def test_alias_forms_find_images_of_main_tag(self):
        self.assertEqual(self.search('машинами'), [self.car])
        self.assertEqual(self.search('машин'), [self.car])

    def test_exact_alias_precedes_newer_tag_lemma_match(self):
        machines_tag = TagPict.objects.create(tag='Машины', slug='lemma-machines')
        machines_picture = self.picture(5005, machines_tag)
        self.assertEqual(self.search('машина'), [self.car, machines_picture])

    def test_fragments_do_not_match_tags_or_aliases(self):
        for query in ('автомоб', 'автомобильн', 'маши'):
            with self.subTest(query=query):
                self.assertEqual(self.search(query), [])

    def test_multiword_tags_are_indexed_per_word_and_terms_use_and(self):
        sea_tag = TagPict.objects.create(tag='Красное море', slug='lemma-red-sea')
        sea_picture = self.picture(5005, sea_tag)
        self.assertEqual(self.search('морями'), [sea_picture])
        self.assertEqual(self.search('красными морями'), [sea_picture])
        self.assertEqual(self.search('красными автомобилями'), [self.car])

    def test_scope_publication_and_numeric_search_are_preserved(self):
        self.assertEqual(self.search('автомобилями', Pict.objects.published().filter(cat=self.other_category)), [])
        with patch('pict.search.lemmatize_search_term') as lemmatizer:
            self.assertEqual(self.search('5001'), [self.car])
            self.assertEqual(self.search('5004'), [])
        lemmatizer.assert_not_called()

    def test_multiple_matching_tags_and_aliases_do_not_duplicate_image(self):
        self.car.tags.add(self.plural_tag)
        TagAlias.objects.create(tag=self.car_tag, alias='Автомобилями')
        self.assertEqual(self.search('автомобилями'), [self.car, self.plural_car])

    def test_alias_move_and_delete_update_search_without_stale_matches(self):
        self.alias.tag = self.plural_tag
        self.alias.save(update_fields={'tag'})
        self.assertEqual(self.search('машинами'), [self.plural_car])
        self.alias.delete()
        self.assertEqual(self.search('машинами'), [])

    def test_database_query_count_does_not_grow_with_morphological_terms(self):
        for query in ('автомобилями', 'красными автомобилями морями лесами закатами'):
            with self.subTest(query=query), self.assertNumQueries(1):
                apply_catalog_search(Pict.objects.published(), parse_search_query(query)).count()
