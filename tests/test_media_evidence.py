"""Protocol fixtures verify projection, without invoking a media process."""

from copy import deepcopy
import json

import pytest

from tiberium_ai.media_evidence import MAX_FFPROBE_BYTES, parse_ffprobe_json


def _payload(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _raw(*, format_name="wav", streams=None):
    return {"format": {"format_name": format_name}, "streams": [] if streams is None else streams}


def _stream(**updates):
    return {"index": 0, "codec_type": "audio", **updates}


def _parse_stream(stream):
    return parse_ffprobe_json(_payload(_raw(streams=[stream])), expected_demuxer="wav")["streams"][0]


def test_wav_native_shape_projects_only_reported_fields():
    raw = {
        "programs": [], "stream_groups": [],
        "streams": [{"index": 0, "codec_name": "pcm_s16le", "codec_type": "audio", "sample_rate": "8000", "channels": 1, "disposition": {"attached_pic": 0}}],
        "format": {"format_name": "wav", "duration": "0.100000"},
    }
    report = parse_ffprobe_json(_payload(raw), expected_demuxer="wav")
    assert set(report) == {"format", "streams", "coverage", "limitations"}
    assert report["format"] == {"name": "wav", "duration_seconds": 0.1}
    assert report["streams"] == [{
        "index": 0, "type": "audio", "codec": "pcm_s16le", "width": None,
        "height": None, "sample_rate": 8000, "channels": 1,
        "duration_seconds": None, "attached_picture": False,
    }]
    assert report["coverage"] == {"streams": "reported_only", "full_decode": "not_established"}
    assert "reported_durations_not_independently_measured" in report["limitations"]


def test_mov_aliases_and_attached_picture_do_not_become_temporal_video_claims():
    raw = _raw(format_name="mov,mp4,m4a,3gp,3g2,mj2", streams=[
        _stream(index=5, codec_type="video", codec_name="mjpeg", width=300, height=300, disposition={"attached_pic": 1}),
        _stream(index=2, codec_name="aac", channels=2, sample_rate="48000"),
    ])
    report = parse_ffprobe_json(_payload(raw), expected_demuxer="mov")
    assert [stream["index"] for stream in report["streams"]] == [2, 5]
    assert report["streams"][1]["attached_picture"] is True
    assert report["format"]["name"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert "video_present" not in report


@pytest.mark.parametrize("demuxer,format_name", [
    ("wav", "wav"), ("flac", "flac"), ("ogg", "ogg"), ("mov", "mov"),
    ("mov", "mp4"), ("mov", "m4a,mp4"), ("mov", "3gp,3g2,mj2"),
])
def test_only_expected_demuxer_alias_family_is_admitted(demuxer, format_name):
    report = parse_ffprobe_json(_payload(_raw(format_name=format_name)), expected_demuxer=demuxer)
    assert report["format"]["name"] == format_name


@pytest.mark.parametrize("demuxer,format_name", [
    ("wav", "mp4"), ("mov", "wav"), ("ogg", "flac"), ("mov", "mov,avi"),
    ("mov", "mov, mp4"), ("wav", "WAV"), ("wav", "wav,wav"), ("mov", ""),
    ("mov", "mov,"), ("wav", None),
])
def test_format_mismatch_cannot_be_normalized_into_a_match(demuxer, format_name):
    with pytest.raises(ValueError):
        parse_ffprobe_json(_payload(_raw(format_name=format_name)), expected_demuxer=demuxer)


def test_empty_stream_list_does_not_attest_absence():
    report = parse_ffprobe_json(_payload(_raw()), expected_demuxer="wav")
    assert report["streams"] == []
    assert report["format"]["duration_seconds"] is None
    assert report["coverage"]["streams"] == "reported_only"
    assert "reported_stream_inventory_may_be_incomplete" in report["limitations"]


def test_missing_optional_fields_and_explicit_zero_are_unknown():
    empty = _parse_stream(_stream())
    zero = _parse_stream(_stream(width=0, height=0, channels=0, sample_rate="0", disposition={}))
    for key in ("codec", "width", "height", "channels", "sample_rate", "duration_seconds", "attached_picture"):
        assert empty[key] is None
        assert zero[key] is None


def test_zero_duration_is_a_reported_zero_not_unknown():
    projected = _parse_stream(_stream(duration="0.000000"))
    assert projected["duration_seconds"] == 0.0


@pytest.mark.parametrize("codec", [None, "N/A", "pcm_s16le", "h264", "A_1"])
def test_codec_nullable_name_contract(codec):
    assert _parse_stream(_stream(codec_name=codec))["codec"] == (None if codec in (None, "N/A") else codec)


@pytest.mark.parametrize("codec", [True, 1, "", "h.264", " pcm_s16le", "é", "x" * 65])
def test_codec_name_is_not_coerced(codec):
    with pytest.raises(ValueError):
        _parse_stream(_stream(codec_name=codec))


@pytest.mark.parametrize("kind", ["audio", "video", "subtitle", "data", "attachment", "unknown"])
def test_reported_stream_types_remain_distinct(kind):
    assert _parse_stream(_stream(codec_type=kind))["type"] == kind


@pytest.mark.parametrize("kind", [None, True, "", "Audio", "timed_video"])
def test_unknown_stream_type_fails(kind):
    with pytest.raises(ValueError):
        _parse_stream(_stream(codec_type=kind))


@pytest.mark.parametrize("index", [True, False, 0.0, "0", -1, 65536, None])
def test_stream_indices_require_strict_bounded_integers(index):
    with pytest.raises(ValueError):
        _parse_stream(_stream(index=index))


def test_indices_are_not_renumbered_and_duplicates_fail():
    assert _parse_stream(_stream(index=65535))["index"] == 65535
    with pytest.raises(ValueError):
        parse_ffprobe_json(_payload(_raw(streams=[_stream(), _stream()])), expected_demuxer="wav")


@pytest.mark.parametrize("field,maximum", [("width", 2**31 - 1), ("height", 2**31 - 1), ("channels", 65535)])
def test_integer_optional_field_boundaries(field, maximum):
    assert _parse_stream(_stream(**{field: maximum}))[field] == maximum
    for value in (True, False, "1", 1.0, None, -1, maximum + 1):
        with pytest.raises(ValueError):
            _parse_stream(_stream(**{field: value}))


@pytest.mark.parametrize("sample_rate", [True, 8000, 8000.0, None, "", "N/A", "+8000", "-1", " 8000", "8e3", "８０００", "2147483648", "0" * 11])
def test_sample_rate_uses_only_bounded_ascii_digit_strings(sample_rate):
    with pytest.raises(ValueError):
        _parse_stream(_stream(sample_rate=sample_rate))


def test_sample_rate_boundaries_and_leading_zeros():
    assert _parse_stream(_stream(sample_rate="2147483647"))["sample_rate"] == 2**31 - 1
    assert _parse_stream(_stream(sample_rate="0008000"))["sample_rate"] == 8000


@pytest.mark.parametrize("duration,expected", [("N/A", None), (".5", 0.5), ("5.", 5.0), ("000.250", 0.25), ("0" * 64, 0.0)])
def test_duration_lexical_contract(duration, expected):
    assert _parse_stream(_stream(duration=duration))["duration_seconds"] == expected


@pytest.mark.parametrize("duration", [None, True, False, 0, 1.5, "", "nan", "NaN", "Infinity", "inf", "1e3", "+1", "-1", "-0", " 1", "1 ", "١", ".", "0" * 65])
def test_invalid_duration_never_becomes_zero_or_confidence(duration):
    with pytest.raises(ValueError):
        _parse_stream(_stream(duration=duration))


def test_format_duration_uses_the_same_contract_as_stream_duration():
    raw = _raw()
    raw["format"]["duration"] = "N/A"
    assert parse_ffprobe_json(_payload(raw), expected_demuxer="wav")["format"]["duration_seconds"] is None
    raw["format"]["duration"] = 0
    with pytest.raises(ValueError):
        parse_ffprobe_json(_payload(raw), expected_demuxer="wav")


@pytest.mark.parametrize("flag", [True, False, "1", 1.0, -1, 2, None])
def test_attached_picture_flag_is_strict(flag):
    with pytest.raises(ValueError):
        _parse_stream(_stream(codec_type="video", disposition={"attached_pic": flag}))


def test_attached_picture_true_requires_reported_video_stream():
    with pytest.raises(ValueError):
        _parse_stream(_stream(disposition={"attached_pic": 1}))
    assert _parse_stream(_stream(disposition={"attached_pic": 0}))["attached_picture"] is False


def test_empty_auxiliary_sections_are_tolerated_only_without_content():
    raw = _raw(streams=[_stream(side_data_list=[{}, {}])])
    raw.update(programs=[], stream_groups=[])
    report = parse_ffprobe_json(_payload(raw), expected_demuxer="wav")
    assert "strict_projection_rejects_unrequested_nonempty_sections" in report["limitations"]
    for key in ("programs", "stream_groups"):
        changed = deepcopy(raw)
        changed[key] = [{}]
        with pytest.raises(ValueError):
            parse_ffprobe_json(_payload(changed), expected_demuxer="wav")
    for value in ([{"side_data_type": "Display Matrix"}], None, {}, [None]):
        changed = deepcopy(raw)
        changed["streams"][0]["side_data_list"] = value
        with pytest.raises(ValueError):
            parse_ffprobe_json(_payload(changed), expected_demuxer="wav")


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.update(error={"code": -1}),
    lambda raw: raw["format"].update(filename="private"),
    lambda raw: raw["streams"][0].update(tags={"comment": "private"}),
    lambda raw: raw["streams"][0].update(disposition={"attached_pic": 0, "default": 1}),
    lambda raw: raw.pop("format"), lambda raw: raw.pop("streams"),
    lambda raw: raw["format"].pop("format_name"),
    lambda raw: raw["streams"][0].pop("index"),
    lambda raw: raw["streams"][0].pop("codec_type"),
])
def test_closed_shapes_and_required_fields(mutation):
    raw = _raw(streams=[_stream()])
    mutation(raw)
    with pytest.raises(ValueError):
        parse_ffprobe_json(_payload(raw), expected_demuxer="wav")


@pytest.mark.parametrize("payload", [
    b"", b"[]", b"null", b"{}", b"{", b"\xff", b"\xef\xbb\xbf{}",
    b'{"format":{"format_name":"wav"},"streams":[],"streams":[]}',
    b'{"format":{"format_name":"wav","duration":NaN},"streams":[]}',
    b'{"format":{"format_name":"wav","duration":1e999},"streams":[]}',
    b'{"format":{"format_name":"wav","format_name":"wav"},"streams":[]}',
    b'{"format":{"format_name":"wav"},"streams":[{"index":0,"codec_type":"audio","disposition":{"attached_pic":0,"attached_pic":1}}]}',
])
def test_invalid_or_ambiguous_json_is_refused(payload):
    with pytest.raises(ValueError):
        parse_ffprobe_json(payload, expected_demuxer="wav")


def test_stream_count_limit_is_exact():
    streams = [_stream(index=index) for index in range(32)]
    assert len(parse_ffprobe_json(_payload(_raw(streams=streams)), expected_demuxer="wav")["streams"]) == 32
    with pytest.raises(ValueError):
        parse_ffprobe_json(_payload(_raw(streams=streams + [_stream(index=32)])), expected_demuxer="wav")


def test_node_and_depth_budgets_precede_projection():
    for extra in ([0] * 2000, [[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]):
        raw = _raw()
        raw["outside_projection"] = extra
        with pytest.raises(ValueError, match="budget"):
            parse_ffprobe_json(_payload(raw), expected_demuxer="wav")


def test_byte_budget_is_exact_and_input_is_repeatable():
    payload = _payload(_raw())
    padded = payload + b" " * (MAX_FFPROBE_BYTES - len(payload))
    first = parse_ffprobe_json(padded, expected_demuxer="wav")
    assert first == parse_ffprobe_json(padded, expected_demuxer="wav")
    with pytest.raises(ValueError):
        parse_ffprobe_json(padded + b" ", expected_demuxer="wav")


@pytest.mark.parametrize("payload,demuxer", [("{}", "wav"), (bytearray(b"{}"), "wav"), (b"{}", None), (b"{}", "mp4"), (b"{}", "WAV"), (b"{}", True)])
def test_api_types_and_expected_demuxer_are_strict(payload, demuxer):
    with pytest.raises(ValueError):
        parse_ffprobe_json(payload, expected_demuxer=demuxer)
