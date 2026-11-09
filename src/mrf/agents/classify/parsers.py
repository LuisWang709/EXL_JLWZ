"""Deterministic static parsers for SAS, R and Python model code. Owner: A1.

No code is executed. Each parser returns a :class:`ParsedCode`; line numbers are 1-based and
refer to the original file (comments are blanked out, never removed, so lines stay aligned).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any

# --------------------------------------------------------------------------- algorithm vocabulary
ALGO_LOGISTIC = "logistic_regression"
ALGO_LINEAR = "linear_regression"
ALGO_TREE = "decision_tree"
ALGO_FOREST = "random_forest"
ALGO_GBM = "gradient_boosting"
ALGO_GLM = "generalized_linear_model"
ALGO_SCORECARD = "scorecard"
ALGO_UNKNOWN = "unknown"

#: algorithms considered compatible when comparing rule vs LLM answers
ALGO_FAMILIES: dict[str, set[str]] = {
    ALGO_LOGISTIC: {ALGO_LOGISTIC, ALGO_SCORECARD, ALGO_GLM},
    ALGO_SCORECARD: {ALGO_SCORECARD, ALGO_LOGISTIC},
    ALGO_LINEAR: {ALGO_LINEAR, ALGO_GLM},
    ALGO_GLM: {ALGO_GLM, ALGO_LOGISTIC, ALGO_LINEAR},
    ALGO_TREE: {ALGO_TREE},
    ALGO_FOREST: {ALGO_FOREST},
    ALGO_GBM: {ALGO_GBM},
}

SAS_PROCS: dict[str, str] = {
    "LOGISTIC": ALGO_LOGISTIC,
    "HPLOGISTIC": ALGO_LOGISTIC,
    "SURVEYLOGISTIC": ALGO_LOGISTIC,
    "PROBIT": ALGO_LOGISTIC,
    "GENMOD": ALGO_GLM,
    "GLIMMIX": ALGO_GLM,
    "REG": ALGO_LINEAR,
    "GLM": ALGO_LINEAR,
    "HPREG": ALGO_LINEAR,
    "GLMSELECT": ALGO_LINEAR,
    "HPSPLIT": ALGO_TREE,
    "HPFOREST": ALGO_FOREST,
    "GRADBOOST": ALGO_GBM,
    "TREEBOOST": ALGO_GBM,
}
SAS_MODEL_PROCS = set(SAS_PROCS)

R_CALLS: dict[str, str] = {
    "glm": ALGO_GLM,
    "lm": ALGO_LINEAR,
    "rpart": ALGO_TREE,
    "ctree": ALGO_TREE,
    "randomForest": ALGO_FOREST,
    "ranger": ALGO_FOREST,
    "xgboost": ALGO_GBM,
    "xgb.train": ALGO_GBM,
    "gbm": ALGO_GBM,
    "scorecard": ALGO_SCORECARD,
}

PY_CLASSES: dict[str, str] = {
    "LogisticRegression": ALGO_LOGISTIC,
    "LogisticRegressionCV": ALGO_LOGISTIC,
    "Logit": ALGO_LOGISTIC,
    "logit": ALGO_LOGISTIC,
    "LinearRegression": ALGO_LINEAR,
    "OLS": ALGO_LINEAR,
    "ols": ALGO_LINEAR,
    "Ridge": ALGO_LINEAR,
    "Lasso": ALGO_LINEAR,
    "GLM": ALGO_GLM,
    "glm": ALGO_GLM,
    "DecisionTreeClassifier": ALGO_TREE,
    "DecisionTreeRegressor": ALGO_TREE,
    "RandomForestClassifier": ALGO_FOREST,
    "RandomForestRegressor": ALGO_FOREST,
    "GradientBoostingClassifier": ALGO_GBM,
    "HistGradientBoostingClassifier": ALGO_GBM,
    "XGBClassifier": ALGO_GBM,
    "XGBRegressor": ALGO_GBM,
    "LGBMClassifier": ALGO_GBM,
    "CatBoostClassifier": ALGO_GBM,
    "train": ALGO_GBM,  # xgb.train / lgb.train - only counted when the module looks like a boosting lib
}

PURPOSE_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("behavioural_score", re.compile(r"(?<![a-z])(behaviou?r\w*|bscore|b_score)", re.I)),
    ("lgd", re.compile(r"(?<![a-z])(lgd|loss[_ ]given[_ ]default|recovery[_ ]rate)", re.I)),
    ("ead", re.compile(r"(?<![a-z])(ead|exposure[_ ]at[_ ]default|ccf|credit[_ ]conversion)(?![a-z])", re.I)),
    ("pricing", re.compile(r"(?<![a-z])(pric\w*|premium|margin|apr)(?![a-z])", re.I)),
    ("fraud", re.compile(r"(?<![a-z])fraud", re.I)),
    ("pd", re.compile(r"(?<![a-z])(pd|prob\w*[_ ]of[_ ]default|default\w*|bad_?flag|delinq\w*|dlq\w*)(?![a-z])", re.I)),
]


def header_comments(text: str, language: str, max_lines: int = 40) -> str:
    """Comment text from the top of the file - where model purpose is usually stated."""
    head = "\n".join(text.split("\n")[:max_lines])
    if language == "sas":
        parts = re.findall(r"/\*(.*?)\*/", head, re.S) + re.findall(r"(?m)^\s*\*([^;]*);", head)
    else:  # r and python both use '#'; python docstrings are added by the caller via ast
        parts = re.findall(r"#(.*)", head)
    return " ".join(parts)


CODE_SUFFIXES = {".sas": "sas", ".r": "r", ".py": "python", ".ipynb": "python"}


@dataclass
class Statement:
    kind: str
    line_start: int
    line_end: int
    text: str


@dataclass
class ParsedCode:
    language: str
    filename: str = ""
    procedures: list[str] = field(default_factory=list)
    algorithm: str = ALGO_UNKNOWN
    target: str | None = None
    features: list[str] = field(default_factory=list)
    class_variables: dict[str, str | None] = field(default_factory=dict)
    statements: list[Statement] = field(default_factory=list)
    datasets_referenced: list[str] = field(default_factory=list)
    purpose_hint: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_model(self) -> bool:
        return self.algorithm != ALGO_UNKNOWN


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _clip(s: str, n: int = 300) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _purpose(header: str, *texts: str | None) -> str | None:
    """Explicit statements in header comments win; then target / file / dataset names."""
    for blob in (header, " ".join(t for t in texts if t)):
        for purpose, pattern in PURPOSE_HINTS:
            if blob and pattern.search(blob):
                return purpose
    return None


# --------------------------------------------------------------------------- language detection
def detect_language(filename: str, text: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in CODE_SUFFIXES:
        return CODE_SUFFIXES[suffix]
    scores = {
        "sas": len(re.findall(r"(?im)^\s*(proc\s+\w+|data\s+[\w.]+\s*;|run\s*;|quit\s*;)", text)),
        "r": len(re.findall(r"<-|library\(|\bfunction\s*\(|~", text)),
        "python": len(re.findall(r"(?m)^\s*(import\s+\w+|from\s+\w+\s+import|def\s+\w+\(|class\s+\w+)", text)),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else "unknown"


# --------------------------------------------------------------------------- SAS
def _blank_text(s: str) -> str:
    """Replace everything except newlines with spaces (keeps line numbers aligned)."""
    return re.sub(r"[^\n]", " ", s)


def _blank(m: re.Match[str]) -> str:
    return _blank_text(m.group(0))


def strip_sas_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)
    # statement comments: '*' at the start of a statement up to the next ';'
    return re.sub(
        r"(?m)(^|;)(\s*)(\*[^;]*;)",
        lambda m: m.group(1) + m.group(2) + _blank_text(m.group(3)),
        text,
    )


def parse_sas(text: str, filename: str = "") -> ParsedCode:
    out = ParsedCode(language="sas", filename=filename)
    code = strip_sas_comments(text)
    if re.search(r"&\w+", code):
        out.warnings.append("macro variables (&name) found; their values are not resolved")
    if re.search(r"(?i)%macro\b", code):
        out.warnings.append("%macro definitions found; macro bodies are parsed as plain code")

    for m in re.finditer(r"(?is)\bdata\s+([\w.]+)\s*;(.*?)\brun\s*;", code):
        for s in re.finditer(r"(?i)\b(set|merge)\s+([\w.]+)", m.group(2)):
            out.datasets_referenced.append(s.group(2))
        out.statements.append(
            Statement("data_step", _line_of(code, m.start()), _line_of(code, m.end()), _clip(text[m.start() : m.end()]))
        )

    for m in re.finditer(r"(?is)\bproc\s+(\w+)\b(.*?)(?:\brun\s*;|\bquit\s*;|(?=\bproc\s+\w)|\Z)", code):
        proc = m.group(1).upper()
        body = m.group(2)
        start, end = _line_of(code, m.start()), _line_of(code, m.end())
        out.statements.append(Statement(f"proc_{proc.lower()}", start, end, _clip(text[m.start() : m.end()])))
        d = re.search(r"(?i)\bdata\s*=\s*([\w.]+)", body)
        if d:
            out.datasets_referenced.append(d.group(1))
        if proc not in SAS_MODEL_PROCS:
            if proc == "SCORE" or re.search(r"(?i)\bwoe\b|scorecard", body):
                out.procedures.append(f"PROC {proc}")
            continue
        out.procedures.append(f"PROC {proc}")
        algo = SAS_PROCS[proc]
        if proc == "GENMOD" and re.search(r"(?i)dist\s*=\s*bin", body):
            algo = ALGO_LOGISTIC
        if out.algorithm in (ALGO_UNKNOWN, ALGO_GLM):
            out.algorithm = algo
        cls = re.search(r"(?is)\bclass\s+([^;]+);", body)
        if cls:
            for var in re.finditer(
                r"(\w+)\s*(?:\(\s*ref\s*=\s*['\"]?([^'\")]+)['\"]?\s*\))?", cls.group(1).split("/")[0]
            ):
                out.class_variables[var.group(1)] = var.group(2)
            if re.search(r"(?i)param\s*=\s*(ref|reference)", cls.group(1)):
                out.warnings.append("CLASS uses reference coding (param=ref)")
            elif proc in {"LOGISTIC", "GENMOD"}:
                out.warnings.append("CLASS without param=ref: SAS default is effect coding for PROC LOGISTIC")
        model = re.search(r"(?is)\bmodel\s+([^;]+);", body)
        if model:
            lhs, _, rhs = model.group(1).partition("=")
            target = re.match(r"\s*(\w+)", lhs)
            if target:
                out.target = out.target or target.group(1)
            event = re.search(r"(?i)event\s*=\s*['\"]([^'\"]+)['\"]", lhs)
            if event:
                out.warnings.append(f"event level '{event.group(1)}' is modelled")
            rhs_vars = rhs.split("/")[0]
            out.features.extend(t for t in re.findall(r"[A-Za-z_]\w*", rhs_vars.replace("|", " ").replace("*", " ")))
            mpos = m.start(2) + model.start()
            out.statements.append(
                Statement(
                    "model", _line_of(code, mpos), _line_of(code, m.start(2) + model.end()), _clip(model.group(0))
                )
            )
    out.features = _dedupe(out.features)
    out.datasets_referenced = _dedupe(out.datasets_referenced)
    out.purpose_hint = _purpose(header_comments(text, "sas"), out.target, filename, " ".join(out.datasets_referenced))
    if not out.statements:
        out.warnings.append("no DATA step or PROC found")
    return out


# --------------------------------------------------------------------------- R
def strip_r_comments(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        in_str: str | None = None
        cut = len(line)
        for i, ch in enumerate(line):
            if in_str:
                if ch == in_str and (i == 0 or line[i - 1] != "\\"):
                    in_str = None
            elif ch in "\"'":
                in_str = ch
            elif ch == "#":
                cut = i
                break
        lines.append(line[:cut] + " " * (len(line) - cut))
    return "\n".join(lines)


def _call_args(code: str, open_pos: int) -> tuple[str, int]:
    """Text inside balanced parentheses starting at ``code[open_pos] == '('``."""
    depth = 0
    for i in range(open_pos, len(code)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return code[open_pos + 1 : i], i
    return code[open_pos + 1 :], len(code)


def _formula(text: str) -> tuple[str | None, list[str], list[str]]:
    m = re.search(r"([\w.]+)\s*~\s*([^,]+)", text)
    if not m:
        return None, [], []
    rhs = m.group(2)
    warnings = []
    if re.search(r"(^|[\s+])\.(\s|$|\+)", rhs):
        warnings.append("formula uses '.' (all columns); feature list needs the data")
    feats = [t for t in re.findall(r"[A-Za-z_][\w.]*", rhs) if t not in {"I", "log", "factor", "poly", "s", "C", "np"}]
    return m.group(1), feats, warnings


def parse_r(text: str, filename: str = "") -> ParsedCode:
    out = ParsedCode(language="r", filename=filename)
    code = strip_r_comments(text)
    for m in re.finditer(r"(?m)\b(library|require)\(\s*['\"]?([\w.]+)", code):
        out.statements.append(Statement("library", _line_of(code, m.start()), _line_of(code, m.start()), m.group(2)))
    names = sorted(R_CALLS, key=len, reverse=True)
    for m in re.finditer(r"(?<![\w.])(" + "|".join(re.escape(n) for n in names) + r")\s*\(", code):
        fn = m.group(1)
        args, end = _call_args(code, m.end() - 1)
        algo = R_CALLS[fn]
        if fn == "glm":
            fam = re.search(r"family\s*=\s*([\w.]+)", args)
            if fam and fam.group(1).startswith(("binomial", "quasibinomial")):
                algo = ALGO_LOGISTIC
            elif fam and fam.group(1).startswith("gaussian"):
                algo = ALGO_LINEAR
        out.procedures.append(f"{fn}(family=binomial)" if fn == "glm" and algo == ALGO_LOGISTIC else f"{fn}()")
        if out.algorithm in (ALGO_UNKNOWN, ALGO_GLM):
            out.algorithm = algo
        target, feats, warns = _formula(args)
        out.target = out.target or target
        out.features.extend(feats)
        out.warnings.extend(warns)
        data = re.search(r"data\s*=\s*([\w.$\[\]\"']+)", args)
        if data:
            out.datasets_referenced.append(data.group(1).strip("\"'"))
        out.statements.append(
            Statement("model", _line_of(code, m.start()), _line_of(code, end), _clip(text[m.start() : end + 1]))
        )
    for m in re.finditer(r"(?:read\.csv|read_csv|readRDS|fread|read_sas)\(\s*['\"]([^'\"]+)", code):
        out.datasets_referenced.append(m.group(1))
    out.features = _dedupe(out.features)
    out.datasets_referenced = _dedupe(out.datasets_referenced)
    out.purpose_hint = _purpose(header_comments(text, "r"), out.target, filename, " ".join(out.datasets_referenced))
    return out


# --------------------------------------------------------------------------- Python
def notebook_to_source(raw: str) -> str:
    nb = json.loads(raw)
    cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
    parts = []
    for c in cells:
        src = c.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        parts.append("\n".join(line for line in src.split("\n") if not line.lstrip().startswith(("%", "!"))))
    return "\n\n".join(parts)


_FEATURE_NAMES = re.compile(r"(?i)^(features?|feature_(cols|columns|names|list)|x_?cols|predictors|covariates|vars)$")
_TARGET_NAMES = re.compile(r"(?i)^(target|target_(col|column|name)|label|y_?col|outcome)$")


def _str_list(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.List | ast.Tuple) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
    ):
        return [e.value for e in node.elts]  # type: ignore[attr-defined]
    return None


def parse_python(text: str, filename: str = "") -> ParsedCode:
    out = ParsedCode(language="python", filename=filename)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        out.warnings.append(f"python syntax error at line {exc.lineno}: falling back to regex")
        for name, algo in PY_CLASSES.items():
            if name != "train" and re.search(rf"\b{name}\s*\(", text):
                out.procedures.append(name)
                if out.algorithm == ALGO_UNKNOWN:
                    out.algorithm = algo
        return out

    boosting_lib = bool(re.search(r"(?m)^\s*(import|from)\s+(xgboost|lightgbm|catboost)", text))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            mod = node.module if isinstance(node, ast.ImportFrom) else ", ".join(a.name for a in node.names)
            out.statements.append(Statement("import", node.lineno, node.end_lineno or node.lineno, str(mod)))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            values = _str_list(node.value)
            if values and _FEATURE_NAMES.match(name):
                out.features.extend(values)
                out.statements.append(
                    Statement("features", node.lineno, node.end_lineno or node.lineno, _clip(ast.unparse(node)))
                )
            elif (
                _TARGET_NAMES.match(name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            ):
                out.target = out.target or node.value.value
            elif name == "y" and isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Constant):
                out.target = out.target or str(node.value.slice.value)
        elif isinstance(node, ast.Call):
            fn = node.func
            call = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
            if call in PY_CLASSES and (call != "train" or boosting_lib):
                out.procedures.append(call)
                algo = PY_CLASSES[call]
                if out.algorithm in (ALGO_UNKNOWN, ALGO_GLM):
                    out.algorithm = algo
                out.statements.append(
                    Statement("model", node.lineno, node.end_lineno or node.lineno, _clip(ast.unparse(node)))
                )
                # statsmodels formula API: smf.logit("y ~ a + b", data=df)
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    target, feats, warns = _formula(node.args[0].value)
                    out.target = out.target or target
                    out.features.extend(feats)
                    out.warnings.extend(warns)
            if call in {"read_csv", "read_parquet", "read_excel", "read_sas"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.datasets_referenced.append(arg.value)
    out.procedures = _dedupe(out.procedures)
    out.features = _dedupe(out.features)
    out.datasets_referenced = _dedupe(out.datasets_referenced)
    out.statements.sort(key=lambda s: s.line_start)
    header = header_comments(text, "python") + " " + (ast.get_docstring(tree) or "")
    out.purpose_hint = _purpose(header, out.target, filename, " ".join(out.datasets_referenced))
    return out


# --------------------------------------------------------------------------- entry point
def parse_source(filename: str, raw: bytes, language_hint: str | None = None) -> ParsedCode:
    """Decode + dispatch. Raises ValueError when the bytes are not text."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 decodes everything
            raise ValueError("file is not text") from exc
    if "\x00" in text:
        raise ValueError("file looks binary")
    if filename.lower().endswith(".ipynb"):
        text = notebook_to_source(text)
    lang = (language_hint or "").lower() or detect_language(filename, text)
    if lang == "sas":
        return parse_sas(text, filename)
    if lang == "r":
        return parse_r(text, filename)
    if lang == "python":
        return parse_python(text, filename)
    return ParsedCode(language="unknown", filename=filename, warnings=["language could not be detected"])
