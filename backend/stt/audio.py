"""Запись из браузера: формат и длительность — до отправки на распознавание.

Сервер не перекодирует запись и не пишет её на диск. Длительность читается из заголовков
контейнера без ffmpeg: так сервер отклоняет длинную запись, не тратя на неё лимит провайдера.

Форматы — те, что отдаёт `MediaRecorder` браузера (docs/contracts/api.md):
- `audio/webm` — Chrome, Android. Длительности в заголовке нет: Chrome пишет запись потоком,
  поэтому она считается по меткам времени блоков.
- `audio/mp4` — Safari, iOS (и Chrome, если попросить). Обычно фрагментированный MP4:
  длительность — по фрагментам (`moof`), а не по общему заголовку.
- `audio/ogg` — Firefox; `audio/wav` — несжатый звук.
"""

import struct
from collections.abc import Iterator

ALLOWED_TYPES = ("audio/webm", "audio/mp4", "audio/ogg", "audio/wav")


def normalize_content_type(value: str | None) -> str:
    """`audio/webm;codecs=opus` → `audio/webm`. Пустой — пустая строка."""
    return (value or "").split(";", 1)[0].strip().lower()


def matches_signature(data: bytes, content_type: str) -> bool:
    """Начало файла совпадает с заявленным форматом — иначе это не аудиозапись."""
    if content_type == "audio/webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if content_type == "audio/mp4":
        return data[4:8] == b"ftyp"
    if content_type == "audio/ogg":
        return data.startswith(b"OggS")
    if content_type == "audio/wav":
        return data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    return False


def duration_seconds(data: bytes, content_type: str) -> float | None:
    """Длительность записи в секундах; `None` — прочитать не удалось (повреждённый файл)."""
    parser = {
        "audio/webm": _webm_duration,
        "audio/mp4": _mp4_duration,
        "audio/ogg": _ogg_duration,
        "audio/wav": _wav_duration,
    }.get(content_type)
    if parser is None:
        return None
    try:
        return parser(data)
    except (IndexError, ValueError, struct.error, ZeroDivisionError):
        return None


# --- WAV ----------------------------------------------------------------------------------


def _wav_duration(data: bytes) -> float | None:
    byte_rate = None
    i = 12
    while i + 8 <= len(data):
        chunk_id = data[i : i + 4]
        size = int.from_bytes(data[i + 4 : i + 8], "little")
        body = i + 8
        if chunk_id == b"fmt " and size >= 16:
            byte_rate = int.from_bytes(data[body + 8 : body + 12], "little")
        elif chunk_id == b"data":
            if not byte_rate:
                return None
            available = len(data) - body
            # Запись потоком: размер 0 или 0xFFFFFFFF — «до конца файла».
            if size in (0, 0xFFFFFFFF) or size > available:
                size = available
            return size / byte_rate
        i = body + size + (size & 1)
    return None


# --- Ogg (Opus, Vorbis) -------------------------------------------------------------------


def _ogg_duration(data: bytes) -> float | None:
    segments = data[26]
    payload_start = 27 + segments
    first_packet = data[payload_start : payload_start + sum(data[27:payload_start])]
    if first_packet.startswith(b"OpusHead"):
        rate, pre_skip = 48000, int.from_bytes(first_packet[10:12], "little")
    elif first_packet.startswith(b"\x01vorbis"):
        rate, pre_skip = int.from_bytes(first_packet[12:16], "little"), 0
    else:
        return None
    # Позиция последнего сэмпла — в последней странице, где закончился пакет (не -1).
    end = len(data)
    while (page := data.rfind(b"OggS", 0, end)) >= 0:
        granule = int.from_bytes(data[page + 6 : page + 14], "little", signed=True)
        if granule >= 0:
            return max(granule - pre_skip, 0) / rate
        end = page
    return None


# --- WebM (Matroska) ----------------------------------------------------------------------

_SEGMENT = 0x18538067
_INFO = 0x1549A966
_CLUSTER = 0x1F43B675
_BLOCK_GROUP = 0xA0
_TIMECODE_SCALE = 0x2AD7B1
_DURATION = 0x4489
_CLUSTER_TIMECODE = 0xE7
_SIMPLE_BLOCK = 0xA3
_BLOCK = 0xA1
# Элементы-контейнеры, внутрь которых заходим. У Chrome размер Segment и Cluster «неизвестен»
# (запись потоком) — поэтому не прыгаем через контейнер, а читаем его детей подряд.
_MASTERS = {_SEGMENT, _INFO, _CLUSTER, _BLOCK_GROUP}


def _vint(data: bytes, i: int, *, keep_marker: bool) -> tuple[int, int, bool]:
    """Число переменной длины EBML: (значение, длина в байтах, «размер неизвестен»)."""
    first = data[i]
    if first == 0:
        raise ValueError("некорректное число EBML")
    length = 9 - first.bit_length()
    if i + length > len(data):
        raise ValueError("число EBML обрезано")
    value = first if keep_marker else first & ((1 << (8 - length)) - 1)
    for byte in data[i + 1 : i + length]:
        value = (value << 8) | byte
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return value, length, unknown


def _webm_duration(data: bytes) -> float | None:
    scale_ns = 1_000_000  # TimecodeScale по умолчанию: метка времени = 1 мс
    declared: float | None = None
    cluster_time = 0
    last_block: int | None = None
    i = 0
    while i < len(data):
        try:
            element, id_len, _ = _vint(data, i, keep_marker=True)
            size, size_len, unknown = _vint(data, i + id_len, keep_marker=False)
        except (ValueError, IndexError):
            break  # обрезанный хвост: считаем по тому, что успели прочитать
        body = i + id_len + size_len
        if element in _MASTERS:
            i = body
            continue
        if unknown:
            break
        payload = data[body : body + size]
        if element == _TIMECODE_SCALE:
            scale_ns = int.from_bytes(payload, "big") or scale_ns
        elif element == _DURATION and size in (4, 8):
            declared = struct.unpack(">f" if size == 4 else ">d", payload)[0]
        elif element == _CLUSTER_TIMECODE:
            cluster_time = int.from_bytes(payload, "big")
        elif element in (_SIMPLE_BLOCK, _BLOCK) and len(payload) >= 4:
            _, track_len, _ = _vint(payload, 0, keep_marker=False)
            relative = int.from_bytes(payload[track_len : track_len + 2], "big", signed=True)
            block_time = cluster_time + relative
            last_block = block_time if last_block is None else max(last_block, block_time)
        i = body + size
    if declared is None and last_block is None:
        return None
    ticks = max(declared or 0.0, float(last_block or 0))
    return ticks * scale_ns / 1e9


# --- MP4 (обычный и фрагментированный) ----------------------------------------------------


def _boxes(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """Боксы MP4 на одном уровне: (тип, начало содержимого, конец)."""
    i = start
    while i + 8 <= end:
        size = int.from_bytes(data[i : i + 4], "big")
        box_type = data[i + 4 : i + 8]
        header = 8
        if size == 1:
            size = int.from_bytes(data[i + 8 : i + 16], "big")
            header = 16
        elif size == 0:
            size = end - i
        if size < header:
            return
        yield box_type, i + header, min(i + size, end)
        i += size


def _find(data: bytes, start: int, end: int, path: list[bytes]) -> tuple[int, int] | None:
    for box_type, body, box_end in _boxes(data, start, end):
        if box_type == path[0]:
            return (body, box_end) if len(path) == 1 else _find(data, body, box_end, path[1:])
    return None


def _time_header(data: bytes, body: int) -> tuple[int, int]:
    """mvhd / mdhd: (timescale, duration)."""
    if data[body] == 1:
        return int.from_bytes(data[body + 20 : body + 24], "big"), int.from_bytes(
            data[body + 24 : body + 32], "big"
        )
    return int.from_bytes(data[body + 12 : body + 16], "big"), int.from_bytes(
        data[body + 16 : body + 20], "big"
    )


def _fragment_end(data: bytes, body: int, end: int, default_duration: int, start: int) -> int:
    """Конец фрагмента (traf) в единицах timescale дорожки."""
    flags = 0
    base = start
    total = 0
    for box_type, b, _ in _boxes(data, body, end):
        if box_type == b"tfhd":
            flags = int.from_bytes(data[b + 1 : b + 4], "big")
            offset = b + 8 + (8 if flags & 0x01 else 0) + (4 if flags & 0x02 else 0)
            if flags & 0x08:
                default_duration = int.from_bytes(data[offset : offset + 4], "big")
        elif box_type == b"tfdt":
            width = 8 if data[b] == 1 else 4
            base = int.from_bytes(data[b + 4 : b + 4 + width], "big")
        elif box_type == b"trun":
            run_flags = int.from_bytes(data[b + 1 : b + 4], "big")
            count = int.from_bytes(data[b + 4 : b + 8], "big")
            offset = b + 8 + (4 if run_flags & 0x01 else 0) + (4 if run_flags & 0x04 else 0)
            if not run_flags & 0x100:
                total += count * default_duration
                continue
            per_sample = 4 * bin(run_flags & 0xF00).count("1")
            for n in range(count):
                at = offset + n * per_sample
                total += int.from_bytes(data[at : at + 4], "big")
    return base + total


def _mp4_duration(data: bytes) -> float | None:
    moov = _find(data, 0, len(data), [b"moov"])
    if moov is None:
        return None
    mdhd = _find(data, *moov, [b"trak", b"mdia", b"mdhd"])
    mvhd = _find(data, *moov, [b"mvhd"])
    trex = _find(data, *moov, [b"mvex", b"trex"])
    if mdhd is None:
        return None
    timescale, track_duration = _time_header(data, mdhd[0])
    seconds = track_duration / timescale
    if mvhd is not None:
        movie_scale, movie_duration = _time_header(data, mvhd[0])
        if movie_scale:
            seconds = max(seconds, movie_duration / movie_scale)
    # Фрагменты: у записи из MediaRecorder общий заголовок обычно с нулевой длительностью.
    default_duration = int.from_bytes(data[trex[0] + 12 : trex[0] + 16], "big") if trex else 0
    fragment_end = 0
    for box_type, body, end in _boxes(data, 0, len(data)):
        if box_type != b"moof":
            continue
        traf = _find(data, body, end, [b"traf"])
        if traf is not None:
            fragment_end = _fragment_end(data, *traf, default_duration, fragment_end)
    return max(seconds, fragment_end / timescale)
