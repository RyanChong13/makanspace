#!/usr/bin/env python3
"""
scripts/check_translations.py
Lists every translatable string used in public/company-facing templates and Python
code that has no entry in build_translations.py, per language.

Usage:  python scripts/check_translations.py            # warn only (exit 0)
        python scripts/check_translations.py --strict   # exit 1 if anything is missing
"""
import ast, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE = ("templates/dashboard/", "venv/", ".venv/", "migrations/")  # dashboard = internal, English only

def norm(s):
    return re.sub(r"\s+", " ", s).strip()

def load_dictionary():
    tree = ast.parse(open(os.path.join(ROOT, "build_translations.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TRANSLATIONS":
            return ast.literal_eval(node.value)
    sys.exit("TRANSLATIONS not found in build_translations.py")

def template_msgids():
    found = {}
    trans = re.compile(r"""\{%\s*trans\s+(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
    block = re.compile(r"\{%\s*blocktrans[^%]*%\}(.*?)\{%\s*endblocktrans\s*%\}", re.S)
    for path in glob.glob(os.path.join(ROOT, "templates/**/*.html"), recursive=True):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if rel.startswith(EXCLUDE):
            continue
        text = open(path, encoding="utf-8").read()
        for m in trans.finditer(text):
            found.setdefault(norm((m.group(1) or m.group(2)).replace('\\"', '"')), set()).add(rel)
        for m in block.finditer(text):
            body = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"%(\1)s", m.group(1))
            parts = [norm(p) for p in re.split(r"\{%\s*plural\s*%\}", body)]
            key = tuple(parts) if len(parts) == 2 else parts[0]
            found.setdefault(key, set()).add(rel)
    return found

def python_msgids():
    found = {}
    call = re.compile(r"""\b(?:gettext(?:_lazy)?|_)\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
    for path in glob.glob(os.path.join(ROOT, "**/*.py"), recursive=True):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if rel.startswith(EXCLUDE) or rel == "build_translations.py":
            continue
        for m in call.finditer(open(path, encoding="utf-8").read()):
            found.setdefault(norm(m.group(1) or m.group(2)), set()).add(rel)
    return found

def main():
    T = load_dictionary()
    used = {**template_msgids(), **python_msgids()}
    normalised = {lang: {(tuple(norm(x) for x in k) if isinstance(k, tuple) else norm(k)) for k in d}
                  for lang, d in T.items()}
    total_missing = 0
    for lang in T:
        missing = sorted((k for k in used if k not in normalised[lang]), key=str)
        total_missing += len(missing)
        print(f"\n[{lang}] {len(T[lang])} entries, {len(missing)} missing")
        for k in missing:
            print(f"   - {k!r}   ({sorted(used[k])[0]})")
    print(f"\n{total_missing} missing translation(s) in total.")
    if total_missing and "--strict" in sys.argv:
        sys.exit(1)

if __name__ == "__main__":
    main()
