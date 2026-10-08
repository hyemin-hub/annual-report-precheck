"""
규칙 baseline: 정정 전 섹션 텍스트에 대해 "비었나 / 해당사항 없음인가 / 첨부 없나 / 너무 짧나"만 판정.
AI 없음. 이 점수가 모든 단계의 비교 기준.

사용:
  python rules/baseline.py data/labels/labels_2025_06-08.tsv
입력 TSV에 before(정정 전 텍스트) 열이 있어야 함. 없으면 reason 열 키워드로 근사(수작업 분류와 같은 기준).
"""
import re, sys
import pandas as pd

EMPTY = re.compile(r"해당\s*사항\s*없음|해당없음|^\s*-\s*$|^\s*$")
MIN_CHARS = {"자기주식": 150, "소수주주권": 100, "공급계약": 150, "재무": 100, "기타": 100}


def section_of(item: str) -> str:
    if re.search(r"XI|공시내용|단일판매|공급계약", item): return "공급계약"
    if re.search(r"VI|Ⅵ|주주총회|소수주주|의사록", item): return "소수주주권"
    if re.search(r"자기주식|주식의 총수", item): return "자기주식"
    if re.search(r"III|Ⅲ|재무", item): return "재무"
    return "기타"


def rule_flag(before: str, item: str, reason: str = "") -> bool:
    sec = section_of(item)
    if isinstance(before, str) and before.strip():
        t = before.strip()
        return bool(EMPTY.search(t)) or len(t) < MIN_CHARS[sec] or "미첨부" in reason
    # before 텍스트가 없으면 사유 키워드로 근사 (1주차 수작업 분류와 동일 기준)
    return bool(re.search(r"미기재|누락|미첨부|미작성|신규작성", reason))


def main(path):
    df = pd.read_csv(path, sep="\t")
    df["section"] = df["item"].map(section_of)
    df["is_pos"] = df["req"].isin(["여", "예"])
    df["flag"] = [rule_flag(b, i, r) for b, i, r in zip(df["before"] if "before" in df.columns else [""] * len(df), df["item"], df["reason"])]
    pos = df[df.is_pos]
    has_text = "before" in df.columns and df["before"].fillna("").str.strip().ne("").any()
    if has_text:
        pos = pos[pos["before"].fillna("").str.strip() != ""]
        print(f"[실제 본문 기준] before 채워진 positive {len(pos)}행만 채점")
    else:
        print("[근사치] before 열 없음. 정정사유 키워드로 근사. 이 숫자는 baseline 아님. scripts/fill_before.py 먼저")
    print("항목별 규칙 recall")
    for sec, g in pos.groupby("section"):
        print(f"  {sec}: {g.flag.sum()}/{len(g)} = {g.flag.mean():.0%}")
    print(f"  전체: {pos.flag.sum()}/{len(pos)} = {pos.flag.mean():.0%}")
    neg = df[~df.is_pos]
    if len(neg):
        print(f"자진정정(부) 행 중 규칙 플래그: {neg.flag.sum()}/{len(neg)}")


if __name__ == "__main__":
    main(sys.argv[1])
