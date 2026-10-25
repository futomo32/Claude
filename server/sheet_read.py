"""Excelのファイル(.xlsx / 古い .xls)を読んで、表を取り出す(2026-10-25 店の指定)。

DMの宛名を Excel で絞り込んだあと、**CSVで保存し直さなくても読み込める**ようにするための
部品。店が普通にExcelで「名前を付けて保存」をすると `.xlsx` になるので、CSVだけしか
読めないと必ず詰まる。

★設計の決めごと
 ・**読み取った表はCSVの文字に直して画面へ返す**(read_to_csv)。画面側は今までどおり
   CSVとして扱えるので、**顧客IDの拾い方・DM送付不可の判定が2つに分かれない**。
   片方だけ直して差が出ると、出してはいけない相手に出てしまう。
 ・**.xlsx は追加の部品を一切使わない**。中身はZIPで固めたXMLなので、Pythonが元から
   持っている zipfile と XML だけで読める。トキワが要るのは「顧客IDの列」だけで、
   書式も計算式も色も要らないため、これで足りる。
   ★2026-08-06、クロネコB2の書き出しが**店のPCに openpyxl が入っていなくて動かなかった**
     ことがあった。**入れるものを増やさない**のがこの店では確実。
 ・**.xls(2003年までの形式)だけは中身の作りがまったく別**で、手書きでは読めない。
   xlrd があれば使い、無ければ**日本語で「CSVか .xlsx で保存し直してください」**と返す
   (今のExcelは、わざわざ選ばない限り .xls では保存しないので、まず出番は無い)。
 ・**形式は拡張子ではなく中身で見分ける**。拡張子だけ直したファイルが実際によくある。
"""

import csv
import io
import zipfile
from xml.etree import ElementTree as ET

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL_DOC = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

MAX_BYTES = 8 * 1024 * 1024   # 受け取るファイルの上限(DMの宛名表なら十分すぎる)
MAX_ROWS = 20000              # 読む行数の上限(顧客は約2万人)
MAX_COLS = 200                # 読む列数の上限

ZIP_HEAD = b"PK\x03\x04"              # .xlsx / .xlsm(ZIP)の目印
OLE_HEAD = b"\xd0\xcf\x11\xe0"        # .xls(2003年まで)の目印


def sniff(data):
    """中身を見て形式を返す: "xlsx" / "xls" / "text"(CSV等)。"""
    if data[:4] == ZIP_HEAD:
        return "xlsx"
    if data[:4] == OLE_HEAD:
        return "xls"
    return "text"


def _col_index(ref):
    """セル番地(例 "AB12")から0始まりの列番号を返す。"""
    n = 0
    for ch in ref:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - 64)
        elif "a" <= ch <= "z":
            n = n * 26 + (ord(ch) - 96)
        else:
            break
    return n - 1 if n else 0


def _num_text(raw):
    """数値のセルを文字にする。★「1.0」ではなく「1」にする
    (顧客IDが数字だけの時、Excelは数値として持つため)。"""
    if raw is None:
        return ""
    s = str(raw).strip()
    try:
        f = float(s)
    except ValueError:
        return s
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return s


def _text_of(el):
    """共有文字列(<si>)やセル内文字列(<is>)を文字にする。

    ★<rPh>(ふりがな)は本文ではないので必ず飛ばすこと。まとめて <t> を拾うと
      「山田 花子ヤマダハナコ」のように**ふりがなが本文に混ざる**(日本語のExcelで
      ふりがな付きのセルは珍しくない)。
    """
    out = []
    for child in el:
        if child.tag == NS_MAIN + "t":
            out.append(child.text or "")
        elif child.tag == NS_MAIN + "r":          # 書式で分かれた塊。中の <t> はつなぐ
            for rt in child:
                if rt.tag == NS_MAIN + "t":
                    out.append(rt.text or "")
        # rPh(ふりがな)・phoneticPr はここで捨てる
    return "".join(out)


def _first_sheet_path(zf, names):
    """1枚目のシートのXMLの在りかを返す。"""
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        sheets = wb.find(NS_MAIN + "sheets")
        rid = sheets[0].get(NS_REL_DOC + "id") if (sheets is not None and len(sheets)) else None
        if rid:
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for r in rels:
                if r.get("Id") == rid:
                    t = (r.get("Target") or "").lstrip("/").replace("./", "")
                    for cand in (t, "xl/" + t):
                        if cand in names:
                            return cand
    except (KeyError, IndexError, ET.ParseError):
        pass   # 作りが違うファイルは、下の素直な探し方に任せる
    for n in sorted(names):
        if n.startswith("xl/worksheets/") and n.endswith(".xml"):
            return n
    raise ValueError("Excelのファイルの中に表(シート)が見つかりませんでした。")


def read_xlsx(data):
    """.xlsx / .xlsm の1枚目のシートを [[文字, ...], ...] で返す(追加の部品は不要)。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise ValueError("Excelのファイルとして読めませんでした(壊れている可能性があります)。")
    with zf:
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            try:
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                shared = [_text_of(si) for si in root.findall(NS_MAIN + "si")]
            except ET.ParseError:
                shared = []
        try:
            sheet = ET.fromstring(zf.read(_first_sheet_path(zf, names)))
        except ET.ParseError:
            raise ValueError("Excelのファイルの中身を読み取れませんでした。")
        sheet_data = sheet.find(NS_MAIN + "sheetData")
        rows = []
        for row in (sheet_data if sheet_data is not None else []):
            cells = []
            for c in row:
                if c.tag != NS_MAIN + "c":
                    continue
                idx = _col_index(c.get("r") or "")
                if idx >= MAX_COLS:
                    continue
                while len(cells) < idx:
                    cells.append("")      # ★空のセルはXMLに出てこない。列の位置を合わせる
                kind = c.get("t")
                if kind == "inlineStr":
                    is_el = c.find(NS_MAIN + "is")
                    cells.append(_text_of(is_el) if is_el is not None else "")
                    continue
                v = c.find(NS_MAIN + "v")
                raw = v.text if v is not None else None
                if kind == "s":                       # 共有文字列(ふつうの文字はこれ)
                    try:
                        cells.append(shared[int(raw)])
                    except (TypeError, ValueError, IndexError):
                        cells.append("")
                elif kind in ("str", "e"):            # 計算式の結果・エラー
                    cells.append(raw or "")
                elif kind == "b":
                    cells.append("1" if raw == "1" else "0")
                else:
                    cells.append(_num_text(raw))
            rows.append(cells)
            if len(rows) >= MAX_ROWS:
                break
        return rows


def read_xls(data):
    """古い .xls(2003年まで)の1枚目のシートを返す。xlrd が無ければ案内して断る。"""
    try:
        import xlrd
    except ImportError:
        raise ValueError(
            "古いExcelの形式(.xls)を読むための部品(xlrd)が入っていません。"
            "Excelで「名前を付けて保存」→ ファイルの種類を「CSV (カンマ区切り)」または"
            "「Excel ブック(.xlsx)」にして保存し直すと、そのまま読み込めます。"
            "(この形式のまま使いたい場合は、コマンドプロンプトで "
            "「py -3 -m pip install xlrd」を実行してください)")
    try:
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(0)
    except Exception as e:   # noqa: BLE001 xlrdの例外は種類が多いのでまとめて日本語にする
        raise ValueError(f"古いExcelの形式(.xls)として読めませんでした: {e}")
    rows = []
    for ri in range(min(sh.nrows, MAX_ROWS)):
        cells = []
        for ci in range(min(sh.ncols, MAX_COLS)):
            val = sh.cell_value(ri, ci)
            cells.append("" if val is None else
                         (_num_text(val) if isinstance(val, float) else str(val)))
        rows.append(cells)
    return rows


def rows_to_csv(rows):
    """読み取った表をCSVの文字にする(画面側は今までどおりCSVとして扱える)。"""
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def read_to_csv(filename, data):
    """Excelのファイルを読んでCSVの文字を返す。読めなければ ValueError(日本語)。
    ★形式は**中身**で見分ける(拡張子だけ直したファイルが実際によくあるため)。"""
    if not data:
        raise ValueError("ファイルが空でした。")
    if len(data) > MAX_BYTES:
        raise ValueError("ファイルが大きすぎます(8MBまで)。")
    kind = sniff(data)
    if kind == "xlsx":
        return rows_to_csv(read_xlsx(data))
    if kind == "xls":
        return rows_to_csv(read_xls(data))
    raise ValueError(
        "Excelのファイル(.xlsx / .xls)として読めませんでした。"
        f"({filename or 'このファイル'} の中身が Excel の形式ではないようです)")
