import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache, reduce
from operator import add
from threading import Lock

from django.db.models import Case, Exists, IntegerField, OuterRef, Value, When


SEARCH_QUERY_PARAMETER = 'q'
SEARCH_QUERY_MAX_LENGTH = 100
SEARCH_TERMS_LIMIT = 5
SEARCH_TERM_MIN_LENGTH = 3
SEARCH_IMAGE_NUMBER_MAX = 2_147_483_647
SEARCH_SEPARATOR_RE = re.compile(r'[\s,#:;–—-]+')
SEARCH_RUSSIAN_WORD_RE = re.compile(r'[а-я]+')
SEARCH_LEMMA_CACHE_SIZE = 2048
_morph_analyzer = None
_morph_analyzer_lock = Lock()


@dataclass(frozen=True)
class ParsedSearchQuery:
    normalized: str
    terms: tuple[str, ...]
    image_number: int | None


def normalize_search_value(value):
    """Приводит тег, синоним или запрос к единому поисковому виду."""
    normalized = unicodedata.normalize('NFKC', value or '')
    normalized = normalized.casefold().replace('ё', 'е')
    return SEARCH_SEPARATOR_RE.sub(' ', normalized).strip()


def _get_morph_analyzer():
    """Лениво загружает один русский словарь на процесс, включая первый параллельный вызов."""
    global _morph_analyzer
    if _morph_analyzer is None:
        with _morph_analyzer_lock:
            if _morph_analyzer is None:
                from pymorphy3 import MorphAnalyzer

                _morph_analyzer = MorphAnalyzer(lang='ru')
    return _morph_analyzer


@lru_cache(maxsize=SEARCH_LEMMA_CACHE_SIZE)
def lemmatize_search_term(term):
    """Выбирает наиболее вероятную лемму нормализованного русского слова."""
    if not SEARCH_RUSSIAN_WORD_RE.fullmatch(term):
        return term
    parsed_words = _get_morph_analyzer().parse(term)
    if not parsed_words:
        return term
    return normalize_search_value(parsed_words[0].normal_form)


def get_search_lemmas(value):
    """Возвращает уникальные леммы слов тега, синонима или поискового запроса."""
    terms = dict.fromkeys(normalize_search_value(value).split())
    return tuple(dict.fromkeys(lemmatize_search_term(term) for term in terms))


def parse_search_query(value):
    terms = tuple(dict.fromkeys(normalize_search_value(value).split()))
    image_number = (
        int(terms[0])
        if len(terms) == 1 and terms[0].isdecimal()
        else None
    )
    return ParsedSearchQuery(
        normalized=' '.join(terms),
        terms=terms,
        image_number=image_number,
    )


def apply_catalog_search(queryset, parsed_query, *, use_lemmatization=True):
    """Строит один AND-запрос по номеру либо по всем словам тега/синонима."""
    if not parsed_query.terms:
        return queryset.none()
    if parsed_query.image_number is not None:
        return queryset.filter(name=parsed_query.image_number)

    through_model = queryset.model.tags.through
    score_expressions = []

    for term in parsed_query.terms:
        picture_tags = through_model.objects.filter(pict_id=OuterRef('pk'))
        primary_exact = picture_tags.filter(tagpict__normalized_tag=term)
        alias_exact = picture_tags.filter(
            tagpict__search_aliases__normalized_alias=term,
        )
        if use_lemmatization:
            lemma = lemmatize_search_term(term)
            primary_lemma = picture_tags.filter(tagpict__search_lemmas__lemma=lemma)
            alias_lemma = picture_tags.filter(
                tagpict__search_aliases__search_lemmas__lemma=lemma,
            )
            match = (
                Exists(primary_exact) | Exists(alias_exact)
                | Exists(primary_lemma) | Exists(alias_lemma)
            )
        else:
            primary_partial = picture_tags.filter(tagpict__normalized_tag__contains=term)
            alias_partial = picture_tags.filter(
                tagpict__search_aliases__normalized_alias__contains=term,
            )
            match = Exists(primary_partial) | Exists(alias_partial)

        queryset = queryset.filter(match)
        score_expressions.append(Case(
            When(Exists(primary_exact), then=Value(4 if use_lemmatization else 3)),
            When(Exists(alias_exact), then=Value(3 if use_lemmatization else 2)),
            default=Value(2 if use_lemmatization else 1),
            output_field=IntegerField(),
        ))

    relevance = reduce(
        add,
        score_expressions,
        Value(0, output_field=IntegerField()),
    )
    return queryset.alias(search_relevance=relevance).order_by(
        '-search_relevance',
        '-id',
    )


def format_image_count(count):
    remainder_100 = count % 100
    remainder_10 = count % 10
    if remainder_10 == 1 and remainder_100 != 11:
        noun = 'изображение'
    elif remainder_10 in {2, 3, 4} and remainder_100 not in {12, 13, 14}:
        noun = 'изображения'
    else:
        noun = 'изображений'
    return f'Найдено {count} {noun}'
