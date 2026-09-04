"""Image URL localization must preserve surrounding markup and deduplicate assets."""

from html.parser import HTMLParser

from lanhu_mcp_server import _localize_image_urls


class _MarkupEvents(HTMLParser):
    """Compare tags and visible text while allowing image source changes."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.events = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.events.append(("start", tag, [(k, v) for k, v in attrs if k != "src"]))

    def handle_startendtag(self, tag, attrs):
        self.events.append(("empty", tag, [(k, v) for k, v in attrs if k != "src"]))

    def handle_endtag(self, tag):
        self.events.append(("end", tag))

    def handle_data(self, data):
        self.events.append(("text", data))


def test_image_after_document_prefix_changes_only_its_source():
    url = "https://assets.lanhuapp.com/permission.png"
    source = (
        '<!doctype html><html><body><main><p>暂无权限</p>'
        f'<img class="permission" src="{url}" alt="权限插图">'
        '</main></body></html>'
    )

    result, mapping = _localize_image_urls(source, "暂无权限")

    assert result == source.replace(url, "./assets/slices/permission.png")
    assert mapping == {"./assets/slices/permission.png": url}
    assert _MarkupEvents(result).events == _MarkupEvents(source).events


def test_multiple_images_preserve_quoted_and_unquoted_attributes():
    urls = [f"https://assets.lanhuapp.com/{name}.png" for name in ("first", "second", "third")]
    source = (
        '<section>before'
        f'<img class="first image" src="{urls[0]}" alt="one">'
        f"<img src='{urls[1]}' class='second' alt='two' />"
        f'<img class=third src={urls[2]} alt=three>'
        'after</section>'
    )
    expected = source
    for url, name in zip(urls, ("first", "second", "third")):
        expected = expected.replace(url, f"./assets/slices/{name}.png")

    result, mapping = _localize_image_urls(source, "mixed attributes")

    assert result == expected
    assert mapping == {f"./assets/slices/{name}.png": url for name, url in zip(("first", "second", "third"), urls)}
    assert _MarkupEvents(result).events == _MarkupEvents(source).events


def test_repeated_image_url_reuses_first_local_path():
    url = "https://assets.lanhuapp.com/shared.svg?version=2"
    source = f'<div><img src="{url}" class="icon-0"><span>label</span><img class=icon-1 src={url}></div>'

    result, mapping = _localize_image_urls(source, "repeated image")

    assert result == source.replace(url, "./assets/slices/icon.svg")
    assert mapping == {"./assets/slices/icon.svg": url}
    assert _MarkupEvents(result).events == _MarkupEvents(source).events


def test_css_background_and_image_share_one_asset_mapping():
    url = "https://assets.lanhuapp.com/shared.webp"
    source = (
        f"<style>.background {{ background-image: url('{url}'); }}</style>"
        f'<div class="background"><img class="preview" src="{url}"></div>'
    )

    result, mapping = _localize_image_urls(source, "shared background")

    assert result == source.replace(url, "./assets/slices/preview.webp")
    assert mapping == {"./assets/slices/preview.webp": url}


def test_css_only_background_uses_selector_as_filename():
    url = "https://assets.lanhuapp.com/background.jpg"
    source = f"<style>.hero {{ background: url('{url}') center / cover; }}</style><div class=hero>Title</div>"

    result, mapping = _localize_image_urls(source, "background only")

    assert result == source.replace(url, "./assets/slices/hero.jpg")
    assert mapping == {"./assets/slices/hero.jpg": url}


def test_existing_local_sources_and_non_image_attributes_are_unchanged():
    source = (
        '<main><img class="icon" src="./assets/icon.svg">'
        '<a href="https://assets.lanhuapp.com/download.png">Download</a>'
        '<img src="data:image/png;base64,AAAA"></main>'
    )

    result, mapping = _localize_image_urls(source, "existing local assets")

    assert result == source
    assert mapping == {}
