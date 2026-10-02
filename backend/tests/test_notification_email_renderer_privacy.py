"""Private opted-in previews must not escape into renderer diagnostics."""
from unittest.mock import Mock

import pytest
from backend.core.api.app.services.email import renderer


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
@pytest.mark.parametrize('succeeds_on_fallback', [True, False])
def test_renderer_error_and_fallback_never_log_preview(monkeypatch, caplog, succeeds_on_fallback):
    marker = 'PRIVATE-NOTIFICATION-PREVIEW'
    outcomes = [ValueError(f'position 1..5: {marker}'), '<html>safe</html>' if succeeds_on_fallback else ValueError(marker)]
    monkeypatch.setattr(renderer, 'mjml2html', Mock(side_effect=outcomes))
    caplog.set_level('DEBUG', logger=renderer.__name__)
    if succeeds_on_fallback:
        assert renderer.convert_mjml_to_html(marker, '{{ preview }}', {'preview': marker}, False) == '<html>safe</html>'
    else:
        with pytest.raises(ValueError, match='Email template conversion failed') as exc:
            renderer.convert_mjml_to_html(marker, '{{ preview }}', {'preview': marker}, False)
        assert marker not in str(exc.value)
    assert marker not in caplog.text


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary,notifications.delivery.email-enabled
def test_rendering_uses_bundled_styles_without_network_fetches(monkeypatch, tmp_path):
    import requests

    template = tmp_path / 'notification.mjml'
    template.write_text('<mjml><mj-body><mj-section><mj-column>'
                        '<mj-text font-family="Ubuntu">{{ preview | e }}</mj-text>'
                        '</mj-column></mj-section></mj-body></mjml>')
    network = Mock(side_effect=AssertionError('Email rendering must not fetch external styles'))
    monkeypatch.setattr(requests, 'get', network)
    rendered = renderer.render_mjml_template(str(tmp_path), 'notification', {'preview': 'Visible preview'})
    assert 'Visible preview' in rendered
    network.assert_not_called()
