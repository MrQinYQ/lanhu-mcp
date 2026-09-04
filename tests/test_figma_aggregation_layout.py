"""Independent source-geometry cases introduced by aggregation designs."""

from copy import deepcopy

import pytest

from lanhu_codegen.figma_dds_layout import infer_dds_layout
def node(identity, x, y, width, height, *, kind="lanhublock", children=(), style=None, **extra):
    result = {"id": identity, "layerId": identity, "type": kind, "componentName": kind,
              "rowDims": {"left": x, "top": y, "width": width, "height": height},
              "props": {"className": identity, "style": {"width": width, "height": height, **(style or {})}},
              "data": {"value": ""}, "children": list(children), **extra}
    if kind == "lanhuimage":
        result["props"]["src"] = f"https://example.test/{identity}.png"
        result["data"]["value"] = result["props"]["src"]
    if kind == "lanhutext":
        result["props"]["text"] = identity
        result["data"]["value"] = identity
    return result


def page(*children, width=400, height=300):
    return node("root", 0, 0, width, height, kind="lanhupage", children=children)


def painted(identity, x, y, width, height, **kwargs):
    return node(identity, x, y, width, height, style={"backgroundColor": "red", **kwargs.pop("style", {})}, **kwargs)


def image(identity, x, y, width=16, height=16, **kwargs):
    return node(identity, x, y, width, height, kind="lanhuimage", **kwargs)


def text(identity, x, y, width=56, height=22):
    return node(identity, x, y, width, height, kind="lanhutext")


def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def by_id(root, identity):
    return next(node for node in walk(root) if node["layerId"] == identity)


def style(node):
    return node["props"]["style"]


def transparent_component(change=None):
    background = node('background', 20, 10, 80, 30,
                      style={'backgroundColor': 'rgba(0,0,0,0)', 'borderRadius': '2px'},
                      ddsTransparentRectProjection=True)
    label = text('label', 28, 13, 64, 24)
    parent = node('component', 20, 0, 80, 50, children=[background, label])
    metadata = {'component': {'id': 'component', 'type': 'artboard', 'layers': [
        {'id': 'background', 'type': 'shapeLayer'}, {'id': 'label', 'type': 'textLayer'}]},
        'background': {'id': 'background', 'type': 'shapeLayer'},
        'label': {'id': 'label', 'type': 'textLayer'}}
    if change == 'scope':
        style(background)['opacity'] = .5
    elif change == 'outside':
        label['rowDims']['width'] = 100
    elif change == 'ordinary':
        background.pop('ddsTransparentRectProjection')
        style(background)['backgroundColor'] = 'red'
    elif change == 'different_component':
        metadata['component']['layers'].pop()
    elif change in ('paint', 'unknown'):
        parent['children'].insert(1, painted('intervening', 30, 15, 20, 15,
                                            style={'filter': 'blur(2px)'} if change == 'unknown' else {}))
    return page(parent), metadata


@pytest.mark.parametrize('change', [None, 'scope', 'outside', 'ordinary', 'different_component', 'paint', 'unknown'])
def test_transparent_rect_adopts_only_its_contained_source_component_text(change):
    source, metadata = transparent_component(change)
    before = deepcopy(source)
    result = infer_dds_layout(source, source_nodes=metadata)
    assert source == before
    background = by_id(result, 'background')
    assert bool(background['children']) is (change is None)
    if change is None:
        assert background['children'][0]['layerId'] == 'label'
        assert style(by_id(result, 'label'))['margin'] == '3px 0 0 8px'
        assert style(background)['backgroundColor'] == 'rgba(0,0,0,0)'


@pytest.mark.parametrize('change', [None, 'partial', 'scope', 'target_scope', 'outside_target', 'later_paint', 'unknown'])
def test_wholly_detached_children_lift_once_preserving_batch_order_and_paint_scope(change):
    first = text('first', 10, 65, 30, 10)
    second = image('second', 45, 80, 10, 10)
    if change == 'partial':
        first['rowDims']['top'] = 55
    children = [text('inside', 10, 10, 30, 10), first, second]
    if change in ('later_paint', 'unknown'):
        children.append(painted('obstacle', 20, 65, 20, 10,
                                style={'filter': 'blur(2px)'} if change == 'unknown' else {}))
    parent = painted('parent', 0, 0, 80, 60, children=children,
                     style={'opacity': .5} if change == 'scope' else {})
    target = painted('target', 0, 0, 100, 70 if change == 'outside_target' else 120,
                     children=[parent], style={'overflow': 'hidden'} if change == 'target_scope' else {})
    source = page(target)
    before = deepcopy(source)
    result = infer_dds_layout(source)
    assert source == before
    first_parent = next(n for n in walk(result) if any(c['layerId'] == 'first' for c in n.get('children', [])))
    if change is None:
        assert first_parent['layerId'] == 'target'
        assert [c['layerId'] for c in by_id(result, 'target')['children']] == ['parent', 'first', 'second']
    else:
        assert 'first' in {n['layerId'] for n in walk(by_id(result, 'parent'))}
    identities = [n['layerId'] for n in walk(result)]
    assert identities.count('first') == identities.count('second') == 1


@pytest.mark.parametrize('change', [None, 'asymmetric', 'different_bottom', 'scope', 'outside', 'paint', 'unknown', 'ambiguous'])
def test_same_bottom_symmetric_band_enters_its_unambiguous_original_sibling_panel(change):
    panel = painted('panel', 30, 20, 120, 180, children=[text('heading', 40, 30, 60, 20)])
    band = painted('band', 20, 160, 140, 40, children=[text('button', 100, 170, 40, 20)])
    if change == 'asymmetric':
        band['rowDims']['width'] += 2
    elif change == 'different_bottom':
        band['rowDims']['top'] -= 2
    elif change == 'scope':
        style(panel)['overflow'] = 'hidden'
    elif change == 'outside':
        style(band)['boxShadow'] = '0 20px 0 red'
    children = [panel]
    if change in ('paint', 'unknown'):
        children.append(painted('intervening', 40, 170, 20, 20,
                                style={'filter': 'blur(2px)'} if change == 'unknown' else {}))
    elif change == 'ambiguous':
        children.append(painted('other-panel', 35, 10, 110, 190, children=[text('other', 40, 15, 50, 20)]))
    children.append(band)
    source = page(painted('application', 0, 0, 200, 200, children=children))
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    assert source == before
    retained = by_id(actual, 'panel')
    assert ('band' in {n['layerId'] for n in walk(retained)}) is (change is None)
    if change is None:
        assert style(retained)['justifyContent'] == 'flex-end'
        assert style(by_id(actual, 'band'))['margin'] == '110px 0 0 -10px'
        assert by_id(actual, 'band')['rowDims'] == band['rowDims']


@pytest.mark.parametrize('change', [None, 'scope', 'unknown', 'later_local', 'later_target', 'outside_target'])
def test_crossing_shadow_popup_promotes_once_and_cannot_jump_past_later_paint(change):
    popup = painted('popup', 80, 30, 50, 30, style={'boxShadow': '0 0 2px red'},
                    children=[text('message', 85, 35, 40, 20)])
    if change == 'unknown':
        style(popup)['boxShadow'] = 'var(--shadow)'
    panel_children = [text('heading', 10, 5, 40, 20), popup]
    if change == 'later_local':
        panel_children.append(painted('local-obstacle', 85, 40, 20, 10))
    panel = painted('panel', 0, 0, 100, 100, children=panel_children,
                     style={'overflow': 'hidden'} if change == 'scope' else {})
    app_children = [panel]
    if change == 'later_target':
        app_children.append(painted('target-obstacle', 110, 40, 20, 10))
    app = painted('app', 0, 0, 120 if change == 'outside_target' else 150, 120, children=app_children)
    actual = infer_dds_layout(page(app))
    if change is None:
        assert by_id(actual, 'app')['children'][-1]['layerId'] == 'popup'
        assert style(by_id(actual, 'popup'))['position'] == 'absolute'
        assert (style(by_id(actual, 'popup'))['left'], style(by_id(actual, 'popup'))['top']) == (80, 30)
    else:
        assert 'popup' in {n['layerId'] for n in walk(by_id(actual, 'panel'))}


@pytest.mark.parametrize('change', [None, 'ordinary', 'wide_pointer', 'scope', 'outside_paint', 'intervening', 'ambiguous'])
def test_popup_terminal_export_pointer_selects_a_cell_without_requiring_body_containment(change):
    cell = painted('cell', 100, 80, 100, 50, children=[text('value', 110, 100, 30, 15)])
    if change == 'scope':
        style(cell)['opacity'] = .5
    body = painted('body', 70, 50, 80, 40, children=[text('message', 80, 60, 60, 20)])
    pointer = image('pointer', 110, 90, 1, 6)
    popup = node('popup', 70, 50, 80, 46, children=[body, pointer], style={'boxShadow': '0 0 2px red'})
    if change == 'outside_paint':
        style(popup)['boxShadow'] = '-100px 0 0 red'
    siblings = [cell]
    if change == 'intervening':
        siblings.append(painted('obstacle', 80, 55, 20, 20))
    elif change == 'ambiguous':
        siblings.append(painted('other-cell', 90, 80, 100, 50, children=[text('other', 150, 100, 30, 15)]))
    siblings.append(popup)
    source = page(painted('panel', 0, 0, 240, 180, children=siblings))
    metadata = {'pointer': {'hasExportDDSImage': change != 'ordinary',
                           'frame': {'left': 110, 'top': 90, 'width': 4 if change == 'wide_pointer' else .001, 'height': 6}}}
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert ('popup' in {n['layerId'] for n in walk(by_id(actual, 'cell'))}) is (change is None)
    if change is None:
        assert style(by_id(actual, 'popup'))['position'] == 'absolute'
        assert (style(by_id(actual, 'popup'))['left'], style(by_id(actual, 'popup'))['top']) == (-30, -30)


def decorated_header(change=None):
    square = painted('square', 14, 6, 16, 16, ddsRectEnvelopeProjection=True)
    half = painted('half', 20, 28, 29, 28, ddsHalfTurnRectProjection=True,
                   style={'boxShadow': '0 7px 19px rgba(0,0,0,.04)'})
    heading = text('heading', 34, 0, 140, 28)
    subtitle = text('subtitle', 96, 52, 200, 24)
    pointer = image('pointer', 10, 19, 8, 9)
    if change == 'ordinary':
        half.pop('ddsHalfTurnRectProjection')
    elif change == 'not_touching':
        heading['rowDims']['height'] -= 1
    elif change == 'overlap':
        heading['rowDims']['height'] += 1
    elif change == 'scope':
        style(half)['opacity'] = .5
    elif change == 'unknown':
        style(half)['filter'] = 'blur(1px)'
    elif change == 'late_square':
        return [half, heading, subtitle, pointer, square]
    return [half, square, pointer, heading, subtitle]


@pytest.mark.parametrize('change', [None, 'ordinary', 'not_touching', 'overlap', 'scope', 'unknown', 'late_square'])
def test_projected_header_connects_only_touching_safe_halfturn_and_preserves_pointer_bounds(change):
    from lanhu_codegen.figma_dds_layout import _projected_header_row
    nodes = decorated_header(change)
    row = _projected_header_row(nodes)
    assert (row is not None) is (change is None)
    if row is not None:
        assert row['rowDims'] == {'left': 10, 'top': 0, 'width': 286, 'height': 76}
        assert [n['layerId'] for n in row['children']] == ['square', 'half', 'heading', 'subtitle', 'pointer']
        assert style(row)['justifyContent'] == 'flex-end'
        assert style(by_id(row, 'pointer'))['position'] == 'absolute'
        assert (style(by_id(row, 'pointer'))['left'], style(by_id(row, 'pointer'))['top']) == (0, 19)
        assert style(by_id(row, 'heading'))['marginLeft'] == -15


@pytest.mark.parametrize('change', [None, 'ordinary', 'scope', 'later_paint', 'later_unknown'])
def test_image_crossing_halfturn_projection_is_overlay_at_original_panel_scope(change):
    from lanhu_codegen.figma_dds_layout import _local_overlays
    half = painted('half', 30, 20, 20, 20, ddsHalfTurnRectProjection=True)
    icon = image('icon', 20, 35, 40, 40)
    if change == 'ordinary':
        half.pop('ddsHalfTurnRectProjection')
    elif change == 'scope':
        style(half)['transform'] = 'rotate(1deg)'
    children = [half, icon]
    if change in ('later_paint', 'later_unknown'):
        children.append(painted('later', 25, 60, 10, 10,
                                style={'filter': 'blur(1px)'} if change == 'later_unknown' else {}))
    panel = painted('panel', 0, 0, 200, 200, children=children)
    assert ('icon' in {n['layerId'] for n in _local_overlays(panel, children, {})}) is (change is None)


@pytest.mark.parametrize('axis', ['row', 'column'])
def test_positive_leading_and_zero_trailing_inset_uses_flex_end_on_either_axis(axis):
    from lanhu_codegen.figma_dds_layout import _place_dds
    children = ([painted('a', 10, 0, 20, 20), painted('b', 40, 0, 60, 20)] if axis == 'row'
                else [painted('a', 0, 10, 20, 20), painted('b', 0, 40, 20, 60)])
    parent = painted('panel', 0, 0, 100, 100, children=children)
    _place_dds(parent, axis)
    assert style(parent)['justifyContent'] == 'flex-end'


@pytest.mark.parametrize('change', [None, 'no_collision', 'real_overlap', 'gap', 'different_width', 'different_rows', 'unknown', 'scope'])
def test_ceil_collision_only_joins_following_integer_twins_with_matching_row_bands(change):
    import math
    from lanhu_codegen.figma_dds_layout import _rounded_following_columns, _place_dds, _group
    source, groups = {}, []
    starts = [(10.5, 29.5), (40, 20), (60, 20)]
    if change == 'no_collision':
        starts[0] = (10, 30)
    elif change == 'real_overlap':
        starts[0] = (10.5, 30)
    elif change == 'gap':
        starts[2] = (61, 20)
    elif change == 'different_width':
        starts[2] = (60, 21)
    for index, (x, width) in enumerate(starts):
        group = []
        for row, (y, height) in enumerate([(0, 20), (20, 30)]):
            if change == 'different_rows' and index == 2:
                y += 1
            identity = f'cell-{index}-{row}'
            raw = {'left': x, 'top': y, 'width': width, 'height': height}
            source[identity] = {'frame': raw}
            item = painted(identity, *(math.ceil(raw[key]) for key in ('left', 'top', 'width', 'height')))
            if index == 1 and change in ('unknown', 'scope'):
                style(item)['filter' if change == 'unknown' else 'opacity'] = 'blur(1px)' if change == 'unknown' else .5
            group.append(item)
        groups.append(group)
    output, special = _rounded_following_columns(groups, source)
    assert bool(special) is (change is None)
    if change is None:
        assert [[n['layerId'] for n in g] for g in output] == [
            ['cell-0-0', 'cell-0-1'], ['cell-2-0', 'cell-1-0', 'cell-2-1', 'cell-1-1']]
        column = _group(output[1], 'column')
        _place_dds(column, 'column')
        assert style(output[1][1])['marginTop'] == -20
        assert style(output[1][3])['marginTop'] == -30


@pytest.mark.parametrize('change', [None, 'no_cursor', 'cursor_outside', 'corner_outside', 'target_scope',
                                    'ancestor_scope', 'positioned_below', 'unknown', 'late_paint', 'ambiguous'])
def test_cursor_menu_adoption_keeps_crossed_static_cell_behind_positioned_control(change):
    target = painted('control', 10, 20, 60, 40,
                     children=[text('label', 20, 30, 20, 10), image('arrow', 50, 30, 10, 10)])
    below = painted('below', 10, 60, 60, 40, children=[text('below-label', 20, 75, 30, 10)])
    menu = painted('menu', 40, 55, 70, 30, style={'boxShadow': '0 0 2px black'},
                   children=[text('option', 50, 65, 50, 10)])
    cursor = image('cursor', 45, 45, 15, 15)
    metadata = {'cursor': {'hasExportDDSImage': change != 'no_cursor'}}
    if change == 'cursor_outside':
        cursor['rowDims']['left'] = 65
    elif change == 'corner_outside':
        menu['rowDims']['top'] = 60
    elif change == 'target_scope':
        style(target)['opacity'] = .5
    elif change == 'positioned_below':
        below['children'].append(painted('overlap', 25, 70, 25, 20))
    elif change == 'unknown':
        style(below)['filter'] = 'var(--filter)'
    children = [target, below, menu]
    if change == 'late_paint':
        children.append(painted('later', 65, 65, 20, 10))
    elif change == 'ambiguous':
        children.insert(1, painted('same-control', 10, 20, 60, 40, children=[text('other', 20, 30, 20, 10)]))
    children.append(cursor)
    panel = painted('panel', 0, 0, 200, 140, children=children,
                    style={'overflow': 'hidden'} if change == 'ancestor_scope' else {})
    source = page(panel)
    before = deepcopy(source)
    actual = infer_dds_layout(source, source_nodes=metadata)
    control = by_id(actual, 'control')
    assert source == before
    assert ('menu' in {n['layerId'] for n in walk(control)}) is (change is None)
    assert len([n for n in walk(actual) if n['layerId'] == 'menu']) == 1
    if change is None:
        assert [n['layerId'] for n in control['children']][-2:] == ['menu', 'cursor']
        assert style(control)['position'] == 'relative'
        assert style(by_id(actual, 'menu'))['position'] == 'absolute'
        assert style(by_id(actual, 'below')).get('position', 'static') == 'static'
        assert (style(by_id(actual, 'menu'))['left'], style(by_id(actual, 'menu'))['top']) == (30, 35)


@pytest.mark.parametrize('change', [None, 'no_border', 'not_full_width', 'later_paint', 'unknown'])
def test_full_width_terminal_border_band_can_cover_earlier_fields_but_not_later_paint(change):
    footer = painted('footer', 0, 70, 180, 30, style={'border': '1px solid red'},
                     children=[text('button', 130, 80, 30, 10)])
    if change == 'no_border':
        style(footer).pop('border')
    elif change == 'not_full_width':
        footer['rowDims']['width'] -= 1
    elif change == 'unknown':
        style(footer)['filter'] = 'var(--filter)'
    children = [text('label', 10, 72, 40, 10), painted('field', 10, 84, 120, 16), footer]
    if change == 'later_paint':
        children.append(painted('later', 100, 80, 20, 15))
    else:
        children.append(painted('scrollbar', 172, 10, 4, 40))
    from lanhu_codegen.figma_dds_layout import _local_overlays
    parent = painted('dialog', 0, 0, 180, 100, children=children)
    assert ('footer' in {n['layerId'] for n in _local_overlays(parent, children, {})}) is (change is None)


@pytest.mark.parametrize('change', [None, 'integer_image', 'ordinary_image', 'later_paint', 'outside'])
def test_subpixel_exported_caret_keeps_its_later_containing_text_absolute(change):
    caret = image('caret', 10, 13, 1, 16)
    label = text('placeholder', 10, 10, 80, 22)
    arrow = image('arrow', 160, 15, 10, 10)
    if change == 'outside':
        label['rowDims']['width'] = 200
    children = [caret, label, arrow]
    if change == 'later_paint':
        children.append(painted('obstacle', 20, 15, 20, 10))
    parent = painted('input', 0, 0, 180, 40, children=children)
    from lanhu_codegen.figma_dds_layout import _local_overlays
    metadata = {'caret': {'hasExportDDSImage': change != 'ordinary_image',
                          'frame': {'width': 1 if change == 'integer_image' else .001}}}
    assert ('placeholder' in {n['layerId'] for n in _local_overlays(parent, children, metadata)}) is (change is None)


@pytest.mark.parametrize('change', [None, 'unknown', 'later_paint'])
def test_known_shadow_popup_overlay_does_not_have_small_icon_area_limit(change):
    body = painted('menu', 10, 30, 170, 100, style={'boxShadow': '0 0 2px black'},
                   children=[text('value', 20, 40, 130, 20)])
    if change == 'unknown':
        style(body)['boxShadow'] = 'var(--shadow)'
    children = [painted('field', 10, 70, 170, 30), body]
    if change == 'later_paint':
        children.append(painted('later', 20, 80, 20, 20))
    from lanhu_codegen.figma_dds_layout import _local_overlays
    parent = painted('panel', 0, 0, 200, 160, children=children)
    assert ('menu' in {n['layerId'] for n in _local_overlays(parent, children, {})}) is (change is None)


@pytest.mark.parametrize('change', [None, 'source_overlap', 'frame_mismatch', 'unknown'])
def test_source_touching_text_and_image_with_ceil_collision_keep_row_flow(change):
    from lanhu_codegen.figma_dds_layout import _arrange_frames, _place_dds
    label = text('value', 11, 10, 30, 20)
    spacer = image('spacer', 40, 10, 4, 20)
    metadata = {'value': {'frame': {'left': 10.5, 'top': 10, 'width': 29.5, 'height': 20}},
                'spacer': {'frame': {'left': 40, 'top': 10, 'width': 4, 'height': 20}}}
    if change == 'source_overlap':
        metadata['value']['frame']['width'] = 30
    elif change == 'frame_mismatch':
        metadata['value']['frame']['left'] = 10
    elif change == 'unknown':
        style(label)['filter'] = 'var(--filter)'
    children, direction = _arrange_frames([label, spacer], metadata)
    assert (direction == 'row') is (change is None)
    if change is None:
        control = painted('control', 0, 0, 60, 40, children=children)
        _place_dds(control, direction)
        assert style(spacer)['margin'] == '10px 16px 0 -1px'


@pytest.mark.parametrize('change', [None, 'left_caption', 'off_center', 'two_texts', 'large_remainder'])
@pytest.mark.parametrize('width', [80, 120])
def test_centered_illustration_caption_uses_odd_remainder_center_without_changing_margins(change, width):
    from lanhu_codegen.figma_dds_layout import _place_dds
    illustration = image('illustration', 20, 21, width, 40)
    caption = text('caption', 20, 69, width, 20)
    style(caption)['textAlign'] = 'left' if change == 'left_caption' else 'center'
    if change == 'off_center':
        caption['rowDims']['left'] += 1
    elif change == 'two_texts':
        illustration = text('illustration-label', 20, 21, width, 40)
    parent = painted('empty-state', 0, 0, width + 40, 113 if change == 'large_remainder' else 111,
                     children=[illustration, caption])
    _place_dds(parent, 'column')
    assert (style(parent).get('justifyContent') == 'flex-center') is (change is None)
    assert style(illustration)['margin'] == '21px 0 0 20px'
    assert style(caption)['margin'] == ('8px 0 24px 20px' if change == 'large_remainder' else
                                      '8px 0 22px 21px' if change == 'off_center' else '8px 0 22px 20px')


def test_caption_beyond_container_bottom_is_not_centered_by_absolute_trailing_gap():
    from lanhu_codegen.figma_dds_layout import _place_dds
    illustration = image('illustration', 20, 21, 80, 40)
    caption = text('caption', 20, 69, 80, 20)
    style(caption)['textAlign'] = 'center'
    parent = painted('empty-state', 0, 0, 120, 67, children=[illustration, caption])
    _place_dds(parent, 'column')
    assert style(parent).get('justifyContent') != 'flex-center'
    assert style(caption)['margin'] == '8px 0 22px 20px'


def test_cursor_menu_cannot_cross_a_cell_that_will_contain_a_forced_projected_overlay():
    target = painted('control', 10, 20, 60, 40,
                     children=[text('label', 20, 30, 20, 10), image('arrow', 50, 30, 10, 10)])
    below = painted('below', 10, 60, 60, 40, children=[
        text('below-label', 20, 75, 30, 10),
        painted('projected-divider', 12, 65, 1, 20, ddsRotatedHairlineProjection=True),
    ])
    menu = painted('menu', 40, 55, 70, 30, style={'boxShadow': '0 0 2px black'},
                   children=[text('option', 50, 65, 50, 10)])
    cursor = image('cursor', 45, 45, 15, 15)
    source = page(painted('panel', 0, 0, 200, 140, children=[target, below, menu, cursor]))
    before = deepcopy(source)
    actual = infer_dds_layout(source, source_nodes={'cursor': {'hasExportDDSImage': True}})
    assert source == before
    assert 'menu' not in {n['layerId'] for n in walk(by_id(actual, 'control'))}
    assert len([n for n in walk(actual) if n['layerId'] == 'menu']) == 1
    assert style(by_id(actual, 'below'))['position'] in {'relative', 'absolute'}
    assert style(by_id(actual, 'projected-divider'))['position'] == 'absolute'
