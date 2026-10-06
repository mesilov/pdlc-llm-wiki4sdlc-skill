#!/usr/bin/env python3
"""Deterministic УТР (ГОСТ Р 58049-2017) violation counter for benchmark runs.

Counts mechanical violations that a regex can catch in Russian text: sentence
length, participles and adverbial participles, passive and nominal predicates,
verbal-noun chains, infinitive steps, singular imperatives, trailing
conditions, slang, unneeded loanwords, filler, synonym rotation.

Known ceiling: this is a regex pass, not a morphological analyzer. Russian
needs one. Without lemmatization the tool works from suffix patterns and
curated word lists, so it BOTH undercounts (no word-order check for 8.2.3.4,
no true noun-chain parse for 8.2.3.10, curated list for adverbial participles)
and can miscount (a few adjectives look like participles by suffix; the
stoplists below remove the frequent ones). Numbers from this tool are
comparable between two texts run through the same version. They are not a
compliance verdict. No tool can guarantee conformance with ГОСТ Р 58049-2017.

Same interface as ste_lint.py: lint(text, text_type) -> dict.

Usage:
  python3 utr_lint.py --type procedural file.md
  cat text.md | python3 utr_lint.py --type descriptive -
  python3 utr_lint.py --self-test
"""
import argparse
import json
import re
import sys

import md_blocks

# Clause 8.2.5.1 / 8.2.6.1: 20 words for BOTH text types. УТР has no 25-word
# descriptive limit, unlike ASD-STE100 rule 6.3.
LIMITS = {"procedural": 20, "descriptive": 20}

RULE_REFS = {
    "sentence_over_limit": "8.2.5.1, 8.2.6.1 — не более 20 слов в предложении",
    "participle": "8.2.3.11 — ограничивать причастия",
    "adverbial_participle": "8.2.3.11 — ограничивать деепричастия",
    "passive_voice": "8.2.3.13 — избегать страдательного залога",
    "nominal_predicate": "8.2.3.10 — глаголы вместо номинативных конструкций",
    "noun_chain": "8.2.3.10 — не более двух существительных подряд",
    "infinitive_step": "8.2.3.9, 8.2.5.3 — повелительное наклонение, не инфинитив",
    "imperative_singular": "8.2.3.9 — повелительное наклонение множественного числа",
    "trailing_condition": "8.2.7 — условие перед командой",
    "slop_word": "8.2.3.1 — простота восприятия (список наш, не из ГОСТа)",
    "slang_metaphor": "8.2.3.5 — запрещены метафоры, сравнения, сленг, жаргон",
    "loanword": "8.2.3.6 — не применять иностранные слова при наличии русских",
    "ui_word": "8.2.3.18 — не использовать слова типа «кнопка», «ссылка»",
    "abbrev_filler": "8.2.3.15 — запрещены сокращения, искажающие смысл",
    "synonym_rotation": "8.2.3.7 — один термин на одно понятие",
}

# --- 8.2.3.11 причастия -----------------------------------------------------
# Active participles (-ущ/-ющ/-ащ/-ящ/-вш) and full passive participles
# (-анн/-янн/-енн/-ённ/-т). Suffix matching, so common adjectives that share
# the ending are excluded by stem.
PARTICIPLE = re.compile(
    r"\b\w{3,}?(?:ущ|ющ|ащ|ящ|вш)(?:ий|его|ему|им|ем|ая|ой|ей|ую|ое|ие|ые|их|ым|ыми|ими)\b"
    r"|\b\w{3,}?(?:анн|янн|енн|ённ)(?:ый|ого|ому|ым|ом|ая|ой|ую|ое|ые|ых|ыми)\b",
    re.I)
# Adjectives and pronouns that match the participle suffixes but are not
# participles in modern usage.
PARTICIPLE_STOP = re.compile(
    r"^(?:следующ|текущ|будущ|предыдущ|настоящ|общ|блестящ|подходящ|данн|"
    r"современн|постоянн|временн|естественн|существенн|ответственн|"
    r"качественн|количественн|единственн|обыкновенн|деревянн|стеклянн|"
    r"промышленн|производственн|государственн|обществен|медленн|длинн|"
    r"ценн|законн|письменн|численн|военн|неизменн|странн)", re.I)

# --- 8.2.3.11 деепричастия --------------------------------------------------
# Curated: suffix -вши/-вшись is unambiguous, the -я forms are a frequency list
# because "-ая/-яя" collides with adjective endings.
ADVERBIAL_PARTICIPLE = re.compile(
    r"\b\w{4,}вши(?:сь)?\b"
    r"|\b(?:использу|учитыва|применя|выполня|запуска|проверя|устанавлива|"
    r"созда|отправля|получа|обеспечива|позволя|нажима|выбира|указыва|"
    r"начина|заканчива|избега|соблюда|игнориру|обновля|удаля|добавля|"
    r"настраива|сохраня|открыва|закрыва)я\b"
    r"|\b(?:исходя|благодаря|несмотря)\b", re.I)

# --- 8.2.3.13 страдательный залог ------------------------------------------
PASSIVE = re.compile(
    r"\b(?:должен|должна|должно|должны)\s+быть\b"
    r"|\b(?:был|была|было|были|будет|будут)\s+\w{3,}(?:ан|ян|ен|ён|т)[аоы]?\b"
    r"|\b(?:осуществля|производ|выполня|использу|устанавлива|настраива|"
    r"проверя|определя|обеспечива|формиру|созда|запуска|обрабатыва|"
    r"отобража|указыва|счита|применя|рассматрива|записыва|передава|"
    r"хран|загружа|сохраня|удаля|добавля|обновля)(?:ется|ются)\b", re.I)

# --- 8.2.3.10 номинативные конструкции --------------------------------------
NOMINAL_PREDICATE = re.compile(
    r"\b(?:явля[ею]тся|представля[ею]т\s+собой)\b"
    r"|\b(?:осуществл|производ|выполн|провед|реализ)\w*\s+\w{4,}(?:ние|ния|ние|"
    r"ция|ции|ки|ку|ования|ование)\b", re.I)
VERBAL_NOUN = r"\w{4,}(?:ния|ния|ения|ания|ции|ости|ства)"
NOUN_CHAIN = re.compile(
    rf"\b{VERBAL_NOUN}\s+{VERBAL_NOUN}\s+\w{{3,}}(?:ния|ения|ания|ции|ости|ства|ов|ей|а|я|и|ы)\b",
    re.I)

# --- 8.2.3.9, 8.2.5.3 повелительное наклонение ------------------------------
INFINITIVE = r"\w{3,}(?:ать|ять|ить|еть|уть|ыть|ти|чь)"
INFINITIVE_STEP = re.compile(
    rf"(?m)^\s*(?:[-*•—]|\d+[.)])\s+{INFINITIVE}\b"
    rf"|\b(?:необходимо|следует|нужно|требуется|рекомендуется|можно|надо)\s+{INFINITIVE}\b"
    rf"|\b(?:должен|должна|должно|должны)\s+{INFINITIVE}\b",
    re.I)
IMPERATIVE_SINGULAR = re.compile(
    r"\b(?:нажми|установи|запусти|проверь|введи|открой|выполни|удали|добавь|"
    r"включи|выключи|настрой|сохрани|перейди|выбери|создай|отправь|укажи|"
    r"скачай|обнови|закрой|останови|перезапусти)\b", re.I)

# --- 8.2.7 условие перед командой -------------------------------------------
TRAILING_COND = re.compile(r"\S[^.!?\n]{3,}[,\s]\s*(?:если|когда|при\s+условии|в\s+случае)\b", re.I)
LEADING_COND = re.compile(r"^(?:если|когда|при\s+условии|в\s+случае)\b", re.I)

# --- наш список воды (не из ГОСТа) ------------------------------------------
SLOP = re.compile(
    r"\b(?:просто|легко|всего\s+лишь|буквально|бесшовно|мощн\w+|надежн\w+|"
    r"надёжн\w+|гибк\w+|комплексн\w+|современн\w+|продвинут\w+|"
    r"необходимо\s+отметить|важно\s+понимать|стоит\s+отметить|"
    r"следует\s+учитывать|на\s+сегодняшний\s+день|в\s+настоящее\s+время|"
    r"в\s+целом|по\s+сути|фактически|как\s+правило|весьма|довольно|"
    r"функционал\w*|данн(?:ый|ая|ое|ого|ому|ой)|вышеуказанн\w+|"
    r"позволя(?:ет|ют)|в\s+целях|с\s+целью|в\s+случае\s+если|"
    r"в\s+связи\s+с\s+тем|посредством|при\s+помощи|нюанс\w*|оптимизир\w+)\b", re.I)
SLANG = re.compile(
    r"\b(?:из\s+коробки|под\s+капотом|на\s+лету|в\s+два\s+клика|"
    r"в\s+пару\s+кликов|магия|магию|заточен\w*|прокача\w+|"
    r"по\s+косточкам|с\s+нуля\s+и\s+до)\b", re.I)
LOANWORD = re.compile(
    r"\b(?:фикс(?:ить|им|ят)|зафиксить|дропну\w+|чекну\w+|юза\w+|апрув\w+|"
    r"мердж\w+|релизит\w*|дебаж\w+|таск[аиу]?|фич[аиу]|кейс[аыу]?|"
    r"пофикс\w+|запуш\w+|заимплемент\w+)\b", re.I)
UI_WORD = re.compile(r"\b(?:кнопк\w+|ссылк\w+)\b", re.I)
ABBREV_FILLER = re.compile(r"и\s*т\.\s*[дп]\.|и\s+пр\.|\betc\.?\b|\bт\.\s*е\.", re.I)

# 8.2.3.7: one term per concept. Each set holds words used for the SAME thing.
# «параметр» is deliberately absent: in software documentation a function
# parameter is a different concept from the settings of a service, so counting
# it as a synonym of «настройка» produced false positives.
ROTATION_SETS = [
    ("check", re.compile(r"\b(провер|убед|удостовер|верифиц|валидир)\w*\b", re.I)),
    ("config", re.compile(r"\b(настройк|конфигурац|опци)\w*\b", re.I)),
]


def strip_code(text):
    """Remove untouchables and collapse each to one word (примечание к 8.2.5.1)."""
    # Blank lines, not spaces: a fence or a heading ends the block around it.
    text = re.sub(r"```.*?```", "\n\n", text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", " КОД ", text)
    text = re.sub(r"^#+\s.*$", "\n\n", text, flags=re.M)  # headings are titles
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"«[^»]{0,80}»", " ЦИТАТА ", text)  # цитируемый текст = одно слово
    return text


def sentences(text):
    """Split into sentences.

    Blocks first (md_blocks), punctuation second: a table row or a list item
    carries no terminal punctuation, so splitting on `.!?:` alone would merge
    a whole table into one 200-word "sentence". Per примечание к 8.2.5.1, text
    in parentheses counts as a separate sentence, so it is pulled out and
    counted on its own.
    """
    parts = []
    for unit in md_blocks.units(text):
        parens = re.findall(r"\(([^)]*)\)", unit)
        unit = re.sub(r"\([^)]*\)", " ", unit)
        parts += re.split(r"(?<=[.!?:])\s+", unit)
        parts += parens
    return [p.strip() for p in parts if p and len(p.strip().split()) >= 2]


def _participles(body):
    return [m for m in PARTICIPLE.finditer(body)
            if not PARTICIPLE_STOP.match(m.group(0))]


def lint(text, text_type):
    body = strip_code(text)
    sents = sentences(body)
    limit = LIMITS[text_type]
    lengths = [len(s.split()) for s in sents]
    counts = {
        "sentence_over_limit": sum(1 for n in lengths if n > limit),
        "participle": len(_participles(body)),
        "adverbial_participle": len(ADVERBIAL_PARTICIPLE.findall(body)),
        "passive_voice": len(PASSIVE.findall(body)),
        "nominal_predicate": len(NOMINAL_PREDICATE.findall(body)),
        "noun_chain": len(NOUN_CHAIN.findall(body)),
        "infinitive_step": len(INFINITIVE_STEP.findall(body)),
        "imperative_singular": len(IMPERATIVE_SINGULAR.findall(body)),
        "trailing_condition": sum(
            1 for s in sents if TRAILING_COND.search(s) and not LEADING_COND.match(s)),
        "slop_word": len(SLOP.findall(body)),
        "slang_metaphor": len(SLANG.findall(body)),
        "loanword": len(LOANWORD.findall(body)),
        "ui_word": len(UI_WORD.findall(body)),
        "abbrev_filler": len(ABBREV_FILLER.findall(body)),
    }
    rotation = 0
    for _, rx in ROTATION_SETS:
        stems = {m.group(1).lower() for m in rx.finditer(body)}
        if len(stems) > 1:
            rotation += len(stems) - 1
    counts["synonym_rotation"] = rotation
    words = max(1, len(body.split()))
    total = sum(counts.values())
    return {
        "type": text_type,
        "words": words,
        "sentences": len(sents),
        "mean_sentence_words": round(sum(lengths) / max(1, len(lengths)), 1),
        "longest_sentence_words": max(lengths, default=0),
        "violations": counts,
        "violations_total": total,
        "violations_per_100w": round(100.0 * total / words, 2),
    }


SLOP_FIXTURE = """Данный сервис является мощным и надежным решением, которое позволяет
осуществлять выполнение синхронизации данных, используя современный протокол передачи,
и при этом работает из коробки практически в два клика. Резервная копия должна быть
создана до миграции, если вы работаете с боевой базой. Необходимо проверить настройки,
а также убедиться, что конфигурация корректна, и т. д. Нажми на кнопку «Продолжить»,
чтобы пофиксить проблему. Сотрудник, отвечающий за релиз, читает журнал.
Для обеспечения выполнения синхронизации таблиц служба ставит задачу в очередь.

- установить пакет;
- запустить миграцию."""

CLEAN_FIXTURE = """Сервис копирует таблицы Postgres в S3. Ему нужен один файл настроек.

Если вы работаете с боевой базой, сначала создайте резервную копию. Затем запустите
миграцию. Проверьте настройки перед запуском."""


# A table and a tight list: no terminal punctuation anywhere, so a
# punctuation-only splitter reports one sentence instead of eight units.
BLOCK_FIXTURE = """| Пункт | Требование |
|---|---|
| 8.2.5.1 | Короткие предложения, максимум 20 слов |
| 8.2.3.7 | Один термин на одно понятие |

- запустите миграцию
- проверьте журнал
- остановите сервис"""

# Prose hard-wrapped at column 60. One sentence, three lines.
WRAP_FIXTURE = """Служба читает строки из Postgres и складывает их
в очередь, затем второй процесс пишет очередь
в S3 одним файлом без промежуточного диска."""


def self_test():
    slop = lint(SLOP_FIXTURE, "procedural")
    clean = lint(CLEAN_FIXTURE, "procedural")
    v = slop["violations"]
    for key in ("sentence_over_limit", "participle", "adverbial_participle",
                "passive_voice", "nominal_predicate", "noun_chain", "infinitive_step",
                "imperative_singular", "trailing_condition", "slop_word",
                "slang_metaphor", "loanword", "ui_word", "abbrev_filler",
                "synonym_rotation"):
        assert v[key] >= 1, (key, slop)
    assert clean["violations_total"] == 0, clean

    # Block splitting: each table cell and list item is its own unit, and no
    # unit is over the limit. Cells of one word are dropped by the >= 2 filter.
    block = lint(BLOCK_FIXTURE, "procedural")
    assert block["sentences"] == 5, block  # 2 text cells + 3 list items
    assert block["longest_sentence_words"] <= 5, block
    assert block["violations"]["sentence_over_limit"] == 0, block

    # Soft-wrapped prose must stay ONE sentence, not three.
    wrap = lint(WRAP_FIXTURE, "descriptive")
    assert wrap["sentences"] == 1, wrap
    assert wrap["longest_sentence_words"] == 22, wrap
    assert wrap["violations"]["sentence_over_limit"] == 1, wrap

    print("self-test OK:", slop["violations_total"],
          "нарушений в «водяном» тексте,", clean["violations_total"], "в чистом;",
          "разбиение по блокам и переносам строк в норме")


def main():
    p = argparse.ArgumentParser(
        description="Счётчик нарушений УТР (ГОСТ Р 58049-2017).")
    p.add_argument("file", nargs="?",
                   help="файл для проверки, «-» — стандартный ввод")
    p.add_argument("--type", choices=sorted(LIMITS), default="descriptive",
                   help="тип текста: инструкция или описательная часть")
    p.add_argument("--refs", action="store_true",
                   help="добавить в вывод номера пунктов ГОСТа")
    p.add_argument("--self-test", action="store_true", help="проверить линтер")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.file:
        p.error("укажите файл или «-» для стандартного ввода")
    text = (sys.stdin.read() if args.file == "-"
            else open(args.file, encoding="utf-8").read())
    out = lint(text, args.type)
    if args.refs:
        out["rule_refs"] = RULE_REFS
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
