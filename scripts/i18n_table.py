#!/usr/bin/env python3
"""Export the panel's UI strings to an English-Russian table and import the edits back.

    python3 scripts/i18n_table.py export translations-en-ru.xlsx
    python3 scripts/i18n_table.py import translations-en-ru.xlsx
    ./web/Dev/build.sh            # rebuild web/index.html after an import

The table has the columns key, section, English and Russian. Only the Russian column is
read back: a row whose Russian text differs from web/src/translations.js is written into
the ru block, every other row is left alone. An empty Russian cell means "keep as is".
Both .xlsx (needs openpyxl) and .csv (UTF-8) work.

Import refuses a row whose placeholders ({name}, {count}...) differ from the English ones,
since the panel would then show a raw {placeholder} or drop a value.
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'web', 'src', 'translations.js')

BLOCK_START = re.compile(r"^ {12}([a-z]{2}): \{\s*$")
KEY_LINE = re.compile(r"^( {16})('?)([A-Za-z0-9_.]+)\2(\s*:\s*)(['\"])(.*)\5(,?)\s*$")
COMMENT = re.compile(r"^ {16}//\s*(.*?)\s*$")
PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_]+\}")
ESCAPE = re.compile(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)")
SIMPLE = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v', '0': '\0'}


def js_unescape(body):
    def rep(m):
        e = m.group(1)
        if e.startswith('u{'):
            return chr(int(e[2:-1], 16))
        if e[0] in 'ux' and len(e) > 1:
            return chr(int(e[1:], 16))
        return SIMPLE.get(e, e)
    return ESCAPE.sub(rep, body)


def js_quote(text):
    out = text.replace('\\', '\\\\').replace("'", "\\'")
    out = out.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    return "'" + out + "'"


def parse(lines):
    """{lang: {key: (value, line_index, section)}}; a later duplicate key wins, as in JS."""
    langs, lang, section = {}, None, ''
    for i, line in enumerate(lines):
        m = BLOCK_START.match(line)
        if m:
            lang, section = m.group(1), ''
            langs[lang] = {}
            continue
        if lang is None:
            continue
        if line.startswith('            }'):
            lang = None
            continue
        c = COMMENT.match(line)
        if c:
            section = c.group(1)
            continue
        k = KEY_LINE.match(line)
        if k:
            langs[lang][k.group(3)] = (js_unescape(k.group(6)), i, section)
    return langs


def read_source():
    with open(SRC, encoding='utf-8') as fh:
        return fh.read().split('\n')


def export(path):
    langs = parse(read_source())
    en, ru = langs['en'], langs.get('ru', {})
    rows = []
    for key, (text, _, section) in sorted(en.items(), key=lambda kv: kv[1][1]):
        rows.append([key, section, text, ru[key][0] if key in ru else ''])
    header = ['key', 'section', 'English', 'Russian']
    if path.lower().endswith('.csv'):
        with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
    else:
        write_xlsx(path, header, rows)
    print(f'{len(rows)} strings written to {path}')


def write_xlsx(path, header, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = 'EN-RU'
    ws.append(header)
    for r in rows:
        ws.append(r)
    bold = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold
        cell.fill = PatternFill('solid', fgColor='DDE4EE')
    widths = {'A': 34, 'B': 26, 'C': 70, 'D': 70}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    wrap = Alignment(wrap_text=True, vertical='top')
    grey = Font(color='808080')
    same = PatternFill('solid', fgColor='FFF2CC')
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
            cell.number_format = '@'
        row[0].font = grey
        row[1].font = grey
        if row[3].value in (None, '') or row[3].value == row[2].value:
            row[3].fill = same
    ws.freeze_panes = 'C2'
    ws.auto_filter.ref = ws.dimensions

    info = wb.create_sheet('Как пользоваться')
    for line in [
        'Правьте только столбец Russian на листе EN-RU. Столбцы key и English не трогайте.',
        'Жёлтым отмечены строки, где русский текст совпадает с английским или пуст.',
        'Слова в фигурных скобках ({name}, {count} и т.п.) должны остаться как есть: панель подставляет туда значения.',
        'Пустая ячейка Russian значит «оставить как сейчас».',
        'Строки можно фильтровать и сортировать, порядок при импорте не важен.',
        'Готовую таблицу пришлите обратно, или выполните: python3 scripts/i18n_table.py import <файл> и затем ./web/Dev/build.sh',
    ]:
        info.append([line])
    info.column_dimensions['A'].width = 120
    wb.save(path)


def read_table(path):
    if path.lower().endswith('.csv'):
        with open(path, encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.reader(fh))
    else:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb['EN-RU'] if 'EN-RU' in wb.sheetnames else wb.worksheets[0]
        rows = [['' if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
    header = [h.strip().lower() for h in rows[0]]
    ki, ri = header.index('key'), header.index('russian')
    return {r[ki].strip(): r[ri] for r in rows[1:] if len(r) > max(ki, ri) and r[ki] and r[ki].strip()}


def do_import(path):
    lines = read_source()
    langs = parse(lines)
    en, ru = langs['en'], langs['ru']
    edits = read_table(path)
    changed, refused, unknown = 0, [], []
    for key, text in edits.items():
        text = text.replace('\r\n', '\n')
        if text.strip() == '':
            continue
        if key not in en:
            unknown.append(key)
            continue
        if key in ru and ru[key][0] == text:
            continue
        if sorted(PLACEHOLDER.findall(text)) != sorted(PLACEHOLDER.findall(en[key][0])):
            refused.append(key)
            continue
        if key in ru:
            i = ru[key][1]
            m = KEY_LINE.match(lines[i])
            lines[i] = f"{m.group(1)}{m.group(2)}{key}{m.group(2)}{m.group(4)}{js_quote(text)},"
        else:
            # a key the ru block lacks goes right after the block's opening line
            start = next(i for i, l in enumerate(lines) if BLOCK_START.match(l) and BLOCK_START.match(l).group(1) == 'ru')
            lines.insert(start + 1, f"                {key}: {js_quote(text)},")
            langs = parse(lines)
            ru = langs['ru']
        changed += 1
    with open(SRC, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    print(f'{changed} Russian strings updated in web/src/translations.js')
    if refused:
        print(f'{len(refused)} rows skipped, their {{placeholders}} differ from English:')
        for k in refused:
            print('   ', k)
    if unknown:
        print(f'{len(unknown)} unknown keys skipped: {", ".join(unknown[:20])}')
    if changed:
        print('Now rebuild the page: ./web/Dev/build.sh')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('export', 'import'):
        print(__doc__)
        sys.exit(2)
    (export if sys.argv[1] == 'export' else do_import)(sys.argv[2])


if __name__ == '__main__':
    main()
