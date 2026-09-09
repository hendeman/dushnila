import re
import unicodedata
from dataclasses import dataclass
from functools import reduce
from operator import add

from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When


SEARCH_QUERY_PARAMETER = 'q'
SEARCH_QUERY_MAX_LENGTH = 100
SEARCH_TERMS_LIMIT = 5
SEARCH_TERM_MIN_LENGTH = 3
SEARCH_IMAGE_NUMBER_MAX = 2_147_483_647
SEARCH_SEPARATOR_RE = re.compile(r'[\s,#:;–—-]+')


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


def apply_catalog_search(queryset, parsed_query):
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
        any_match = picture_tags.filter(
            Q(tagpict__normalized_tag__contains=term)
            | Q(tagpict__search_aliases__normalized_alias=term)
        )

        queryset = queryset.filter(Exists(any_match))
        score_expressions.append(Case(
            When(Exists(primary_exact), then=Value(3)),
            When(Exists(alias_exact), then=Value(2)),
            default=Value(1),
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
