"""
공통 채점기. 어떤 방법(규칙/LLM/로컬)이든 같은 형식의 예측 파일을 내면 여기서 점수를 냄.

예측 파일 형식 (TSV): rcp_no, item, flag(0/1), evidence(근거로 짚은 문단 텍스트, 없으면 빈칸)
정답 파일: data/labels/*.tsv (req 열이 여/예면 positive)

사용:
  python eval/score.py --pred llm/pred.tsv --gold data/labels/labels_2025_06-08.tsv --method "규칙+LLM(gpt-4o-mini)"
→ 항목별 recall, 오탐/100, 근거겹침을 출력하고 eval/results.csv에 한 줄 추가
"""
import argparse, csv, datetime
import pandas as pd
import sys; sys.path.insert(0, "rules"); from baseline import section_of  # noqa


def overlap(evidence: str, after: str) -> bool:
    if not isinstance(evidence, str) or not isinstance(after, str) or not evidence.strip():
        return False
    ev = set(evidence.split()); af = set(after.split())
    return len(ev & af) / max(1, len(ev)) >= 0.3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True); ap.add_argument("--gold", required=True)
    ap.add_argument("--method", required=True); ap.add_argument("--note", default="")
    a = ap.parse_args()
    gold = pd.read_csv(a.gold, sep="\t"); pred = pd.read_csv(a.pred, sep="\t")
    df = gold.merge(pred, on=["rcp_no", "item"], how="left")
    df["flag"] = df["flag"].fillna(0).astype(int)
    df["section"] = df["item"].map(section_of)
    df["is_pos"] = df["req"].isin(["여", "예"])
    pos, neg = df[df.is_pos], df[~df.is_pos]
    rec = {s: (g.flag.sum() / len(g) if len(g) else float("nan")) for s, g in pos.groupby("section")}
    fp100 = 100 * neg.flag.mean() if len(neg) else float("nan")
    ev = [overlap(e, af) for e, af in zip(pos.get("evidence", [""] * len(pos)), pos.get("after", [""] * len(pos)))]
    ev_rate = sum(ev) / len(ev) if ev else float("nan")
    print("recall:", {k: f"{v:.0%}" for k, v in rec.items()}, "| 오탐/100:", f"{fp100:.1f}", "| 근거겹침:", f"{ev_rate:.0%}")
    with open("eval/results.csv", "a", newline="") as f:
        csv.writer(f).writerow([datetime.date.today().isoformat(), a.method,
                                *[f"{rec.get(k, float('nan')):.3f}" for k in ["자기주식", "소수주주권", "공급계약", "재무"]],
                                f"{fp100:.2f}", f"{ev_rate:.3f}", len(pos), len(neg), a.note])


if __name__ == "__main__":
    main()
