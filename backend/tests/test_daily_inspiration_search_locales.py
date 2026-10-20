"""The UI's locale names are not always valid Brave API language enum values."""
import ast
from pathlib import Path
from typing import Dict

import pytest


def source_locale_mapper():
    source = Path(__file__).resolve().parents[1] / 'apps/ai/daily_inspiration/generator.py'
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if
             isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
             and node.target.id == '_LANGUAGE_TO_SEARCH_PARAMS'
             or isinstance(node, ast.FunctionDef) and node.name == 'get_search_params_for_language']
    scope = {'Dict': Dict}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope['get_search_params_for_language']


@pytest.mark.parametrize('locale,country,language', [
    ('zh', 'cn', 'zh-hans'), ('zh-CN', 'cn', 'zh-hans'),
    ('pt', 'br', 'pt-br'), ('pt_BR', 'br', 'pt-br'),
    ('id', 'id', 'en'), ('no', 'no', 'nb'),
    ('vi', 'all', 'vi'), ('th', 'all', 'th'), ('cs', 'all', 'cs'),
    ('he', 'all', 'he'), ('uk', 'all', 'uk'), ('ro', 'all', 'ro'), ('hu', 'all', 'hu'),
])
# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_locale_variants_use_supported_brave_language_values(locale, country, language):
    assert source_locale_mapper()(locale) == {'country': country, 'search_lang': language}


# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_every_feed_locale_maps_to_the_observed_native_brave_language_enum():
    # Captured from Brave's authoritative validation response during the live
    # qualification on 2026-10-20; zh/pt/id must never silently return HTTP422.
    supported = set('ar eu bn bg ca zh-hans zh-hant hr cs da nl en en-gb et fi fr gl de el gu he hi hu is it ja jp kn ko lv lt ms ml mr nb pl pt-br pt-pt pa ro ru sr sk sl es sv ta te th tr uk vi'.split())
    countries = set('AR AU AT BE BR CA CL DK FI FR DE GR HK IN ID IT JP KR MY MX NL NZ NO CN PL PT PH RU SA ZA ES SE CH TW TR GB US ALL'.split())
    for locale in 'en de zh es fr pt ru ja ko it tr vi id pl nl ar hi th cs sv'.split():
        parameters = source_locale_mapper()(locale)
        assert parameters['search_lang'] in supported
        assert parameters['country'].upper() in countries
