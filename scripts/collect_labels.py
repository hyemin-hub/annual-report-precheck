"""
[기재정정] 사업보고서 목록을 받고, 각 건의 정정신고 표지에서
(항목 / 정정요구ㆍ명령 관련 여부 / 정정사유 / 정정 전 / 정정 후) 행을 뽑아 TSV로 저장.

사용:
  python scripts/collect_labels.py --start 20250601 --end 20250831 --out data/labels/labels_2025_06-08.tsv

주의:
  - DART는 짧은 시간에 수백 건 요청하면 차단함. 건당 0.5초 이상 쉬게 돼 있음
  - 표지 서식이 회사마다 조금 달라 일부는 파싱 실패함. 실패 건은 failed.txt에 접수번호 기록
  - OpenDART 키는 .env의 OPENDART_API_KEY
"""
import argparse, csv, os, re, time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["OPENDART_API_KEY"]
LIST = "https://opendart.fss.or.kr/api/list.json"
MAIN = "https://dart.fss.or.kr/dsaf001/main.do"
VIEW = "https://dart.fss.or.kr/report/viewer.do"
UA = {"User-Agent": "Mozilla/5.0 (dart-precheck; student project)"}


def list_reports(start, end):
    """정기공시(A) 중 보고서명에 '사업보고서'가 들어간 것. 최종보고서 여부와 무관하게 전부."""
    page, out = 1, []
    while True:
        r = requests.get(LIST, params=dict(crtfc_key=KEY, bgn_de=start, end_de=end,
                                           pblntf_ty="A", last_reprt_at="N",
                                           page_no=page, page_count=100), timeout=30).json()
        for it in r.get("list", []):
            if "사업보고서" in it["report_nm"]:
                out.append(it)
        if page >= int(r.get("total_page", 1)):
            break
        page += 1
    return out


def cover_rows(rcp_no):
    """정정신고 표지의 정정사항 표에서 행 추출."""
    m = requests.get(MAIN, params=dict(rcpNo=rcp_no), headers=UA, timeout=30).text
    g = lambda k: (re.search(r"node1\['%s'\]\s*=\s*\"([^\"]+)\"" % k, m) or [None, None])[1]
    if not g("dcmNo"):
        return None
    v = requests.get(VIEW, params=dict(rcpNo=rcp_no, dcmNo=g("dcmNo"), eleId=g("eleId"),
                                       offset=g("offset"), length=g("length"), dtd=g("dtd")),
                     headers=UA, timeout=30).text
    soup = BeautifulSoup(v, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) >= 5 and re.fullmatch(r"(여|부|예|아니오)", tds[1]):
            rows.append(dict(item=tds[0], req=tds[1], reason=tds[2],
                             before=tds[3][:2000], after=tds[4][:2000]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--sleep", type=float, default=0.7)
    a = ap.parse_args()
    reps = [r for r in list_reports(a.start, a.end) if "기재정정" in r["report_nm"]]
    print(f"[기재정정] 사업보고서 {len(reps)}건")
    failed = []
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rcp_no", "corp_code", "corp_name", "rcept_dt",
                                          "item", "req", "reason", "before", "after"], delimiter="\t")
        w.writeheader()
        for i, r in enumerate(reps, 1):
            try:
                rows = cover_rows(r["rcept_no"])
            except Exception as e:
                rows = None
            if not rows:
                failed.append(r["rcept_no"])
            else:
                for row in rows:
                    w.writerow(dict(rcp_no=r["rcept_no"], corp_code=r["corp_code"],
                                    corp_name=r["corp_name"], rcept_dt=r["rcept_dt"], **row))
            if i % 20 == 0:
                print(i, "done,", len(failed), "failed")
            time.sleep(a.sleep)
    open(a.out.replace(".tsv", "_failed.txt"), "w").write("\n".join(failed))
    print("완료. 실패", len(failed))


if __name__ == "__main__":
    main()
