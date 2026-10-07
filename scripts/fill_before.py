"""
라벨 표의 각 행(정정신고서 접수번호 + 항목)에 대해
  before = 정정 전 원본 사업보고서의 해당 섹션 본문
  after  = 정정신고서(정정 후)의 해당 섹션 본문
을 DART 뷰어에서 가져와 채움. 이게 채워져야 rules/baseline.py가 실제 본문 위에서 돌아감.

사용:
  python scripts/fill_before.py --labels data/labels/labels_2025_06-08.tsv --out data/labels/labels_2025_06-08_text.tsv
  (중간에 끊겨도 --out 파일이 있으면 채워진 행은 건너뜀. 다시 실행하면 이어서 함)

동작:
  1. 정정신고서 rcp_no → main.do에서 목차(node 목록: 제목, dcmNo, eleId, offset, length) 파싱
  2. OpenDART list.json으로 같은 회사의 직전 '사업보고서'(기재정정 아닌 것) 접수번호를 찾음 → 원본
  3. 항목 문자열("Ⅰ. 회사의 개요 4. 주식의 총수 등 라. 자기주식에 관한 사항")과 목차 제목을 맞춰
     가장 깊게 일치하는 노드를 고름. 원본·정정본 각각 viewer.do로 본문 텍스트 추출
  4. before/after 열에 저장. 못 찾으면 빈칸 + note 열에 사유

주의:
  - DART는 수백 건 연속 요청 시 차단. 건당 1초 쉼. 122행이면 원본+정정본 합쳐 20분 안팎
  - 원본 사업보고서가 조회기간(접수일 기준 과거 400일) 안에 없으면 note에 'no_orig'
  - 목차 제목이 회사마다 조금 달라 일부는 섹션 매칭 실패함. note에 'no_node'. 그 행은 손으로 확인
"""
import argparse, os, re, sys, time, datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ.get("OPENDART_API_KEY", "")
LIST = "https://opendart.fss.or.kr/api/list.json"
MAIN = "https://dart.fss.or.kr/dsaf001/main.do"
VIEW = "https://dart.fss.or.kr/report/viewer.do"
UA = {"User-Agent": "Mozilla/5.0 (annual-report-precheck; student project)"}
MAX_CHARS = 8000

_toc_cache, _orig_cache = {}, {}


def toc(rcp_no):
    """main.do의 자바스크립트 node 목록 → [{text, dcmNo, eleId, offset, length, dtd}]"""
    if rcp_no in _toc_cache:
        return _toc_cache[rcp_no]
    html = requests.get(MAIN, params=dict(rcpNo=rcp_no), headers=UA, timeout=30).text
    nodes = {}
    for n, k, v in re.findall(r"node(\d+)\['(\w+)'\]\s*=\s*\"([^\"]*)\"", html):
        nodes.setdefault(int(n), {})[k] = v
    out = [d for _, d in sorted(nodes.items()) if d.get("dcmNo") and d.get("text")]
    _toc_cache[rcp_no] = out
    return out


def viewer_text(rcp_no, node):
    v = requests.get(VIEW, params=dict(rcpNo=rcp_no, dcmNo=node["dcmNo"], eleId=node["eleId"],
                                       offset=node["offset"], length=node["length"], dtd=node.get("dtd", "dart3.xsd")),
                     headers=UA, timeout=30).text
    soup = BeautifulSoup(v, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    text = re.sub(r"[ \t　]+", " ", soup.get_text("\n", strip=True))
    text = re.sub(r"\n{2,}", "\n", text)
    return text[:MAX_CHARS]


ROMAN = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "Ⅵ": "VI", "Ⅶ": "VII",
         "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X", "Ⅺ": "XI", "Ⅻ": "XII"}


def norm(s):
    s = str(s)
    for k, v in ROMAN.items():
        s = s.replace(k, v)
    return re.sub(r"[\s\.\,ㆍ·\(\)]", "", s)


def pick_node(nodes, item):
    """항목 문자열 안에 제목이 포함되는 노드 중, 항목 문자열에서 가장 뒤에 나오는 것(=가장 깊은 섹션).
    같은 위치면 제목이 긴 쪽."""
    it = norm(item)
    best, best_key = None, (-1, -1)
    for nd in nodes:
        t = norm(nd["text"])
        if len(t) >= 4:
            pos = it.find(t)
            if pos >= 0 and (pos, len(t)) > best_key:
                best, best_key = nd, (pos, len(t))
    return best


def find_original(corp_code, rcept_dt):
    """같은 회사의, 정정신고 접수일 이전 400일 안에서 가장 최근 '사업보고서'(기재정정 제외) 접수번호."""
    key = (corp_code, rcept_dt)
    if key in _orig_cache:
        return _orig_cache[key]
    if not KEY:
        return None
    end = datetime.datetime.strptime(str(rcept_dt), "%Y%m%d")
    bgn = (end - datetime.timedelta(days=400)).strftime("%Y%m%d")
    r = requests.get(LIST, params=dict(crtfc_key=KEY, corp_code=corp_code, bgn_de=bgn,
                                       end_de=end.strftime("%Y%m%d"), pblntf_ty="A",
                                       last_reprt_at="N", page_count=100), timeout=30).json()
    cands = [x for x in r.get("list", []) if "사업보고서" in x["report_nm"]
             and "기재정정" not in x["report_nm"] and x["rcept_no"] < str(rcept_dt) + "999999"]
    cands.sort(key=lambda x: x["rcept_no"], reverse=True)
    orig = cands[0]["rcept_no"] if cands else None
    _orig_cache[key] = orig
    return orig


def corp_code_of(rcp_no, corp_name):
    """라벨 표에 corp_code가 없을 때: 정정신고서 main.do 안의 corpCode 값으로 대체."""
    html = requests.get(MAIN, params=dict(rcpNo=rcp_no), headers=UA, timeout=30).text
    m = re.search(r"corpCode['\"]?\s*[:=]\s*['\"](\d{8})", html) or re.search(r"corp_code=(\d{8})", html)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--only-pos", action="store_true", help="req가 여/예인 행만")
    a = ap.parse_args()

    df = pd.read_csv(a.labels, sep="\t", dtype=str).fillna("")
    df = df.rename(columns={"rcp": "rcp_no", "corp": "corp_name"})  # 브라우저 수집본 호환
    if a.only_pos:
        df = df[df["req"].isin(["여", "예"])].copy()
    for c in ["before", "after", "orig_rcp_no", "note"]:
        if c not in df.columns:
            df[c] = ""
    if os.path.exists(a.out):  # 이어하기
        done = pd.read_csv(a.out, sep="\t", dtype=str).fillna("")
        key = ["rcp_no", "item"]
        df = df.merge(done[key + ["before", "after", "orig_rcp_no", "note"]], on=key, how="left", suffixes=("", "_d"))
        for c in ["before", "after", "orig_rcp_no", "note"]:
            df[c] = df[c + "_d"].where(df[c + "_d"] != "", df[c]); df.drop(columns=[c + "_d"], inplace=True)

    n_total = len(df)
    for i, row in df.iterrows():
        if row["before"] or row["note"]:
            continue
        rcp = row["rcp_no"]; notes = []
        try:
            nodes_after = toc(rcp)
            rcept_dt = row.get("rcept_dt") or rcp[:8]
            corp_code = row.get("corp_code") or corp_code_of(rcp, row.get("corp_name", ""))
            orig = find_original(corp_code, rcept_dt) if corp_code else None
            df.at[i, "orig_rcp_no"] = orig or ""
            nd_after = pick_node(nodes_after, row["item"])
            if nd_after:
                df.at[i, "after"] = viewer_text(rcp, nd_after); time.sleep(a.sleep)
            else:
                notes.append("no_node_after")
            if orig:
                nd_before = pick_node(toc(orig), row["item"])
                if nd_before:
                    df.at[i, "before"] = viewer_text(orig, nd_before); time.sleep(a.sleep)
                else:
                    notes.append("no_node_before")
            else:
                notes.append("no_orig")
        except Exception as e:
            notes.append(f"err:{type(e).__name__}")
        df.at[i, "note"] = ";".join(notes) if notes else "ok"
        if (i + 1) % 10 == 0 or i == n_total - 1:
            df.to_csv(a.out, sep="\t", index=False)
            filled = (df["before"] != "").sum()
            print(f"{i + 1}/{n_total} 처리, before 채움 {filled}", flush=True)
        time.sleep(a.sleep)
    df.to_csv(a.out, sep="\t", index=False)
    print("완료. note 분포:"); print(df["note"].value_counts())


if __name__ == "__main__":
    main()
